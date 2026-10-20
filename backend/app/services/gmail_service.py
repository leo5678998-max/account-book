import os
import json
import base64
from typing import List, Dict, Any, Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from sqlalchemy.orm import Session
from ..models import SystemSetting

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

class GmailService:
    def __init__(self, db: Session):
        self.db = db

    def _get_setting(self, key: str) -> Optional[str]:
        item = self.db.query(SystemSetting).filter(SystemSetting.key == key).first()
        return item.value if item else None

    def _set_setting(self, key: str, value: str, desc: str = ""):
        item = self.db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not item:
            item = SystemSetting(key=key, value=value, description=desc)
            self.db.add(item)
        else:
            item.value = value
        self.db.commit()

    def get_client_config(self) -> Dict[str, Any]:
        """讀取 Google OAuth Client 設定 (優先從 DB，次之從環境變數)"""
        client_id = self._get_setting("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = self._get_setting("GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET", "")
        redirect_uri = self._get_setting("GOOGLE_REDIRECT_URI") or os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
        
        return {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        }

    def get_auth_url(self, redirect_uri: Optional[str] = None) -> str:
        """產生讓使用者授權的 Google 登入網址"""
        client_config = self.get_client_config()
        if not client_config["web"]["client_id"]:
            raise ValueError("尚未設定 GOOGLE_CLIENT_ID 與 GOOGLE_CLIENT_SECRET")

        if redirect_uri:
            client_config["web"]["redirect_uris"] = [redirect_uri]

        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=client_config["web"]["redirect_uris"][0]
        )
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent' # 強制取得 refresh token
        )
        return auth_url

    def handle_auth_callback(self, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """使用者完成 Google 授權後，換取 Access/Refresh Token 並持久化到 DB"""
        client_config = self.get_client_config()
        if redirect_uri:
            client_config["web"]["redirect_uris"] = [redirect_uri]

        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=client_config["web"]["redirect_uris"][0]
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials

        token_data = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
        self._set_setting("GOOGLE_TOKENS", json.dumps(token_data), "Gmail OAuth Tokens")
        return {"status": "success", "message": "Google 帳號已成功授權串接"}

    def get_credentials(self) -> Optional[Credentials]:
        """載入儲存的 Google 憑證，並在過期時自動刷新"""
        tokens_json = self._get_setting("GOOGLE_TOKENS")
        if not tokens_json:
            return None

        try:
            data = json.loads(tokens_json)
            creds = Credentials(
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=data.get("client_id"),
                client_secret=data.get("client_secret"),
                scopes=data.get("scopes", SCOPES)
            )

            # 檢查並自動更新 Token
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                data["token"] = creds.token
                self._set_setting("GOOGLE_TOKENS", json.dumps(data), "Gmail OAuth Tokens")

            return creds
        except Exception as e:
            print(f"[GmailService] 憑證載入或刷新失敗: {e}")
            return None

    def is_connected(self) -> bool:
        creds = self.get_credentials()
        return creds is not None and creds.valid

    def fetch_dbs_bill_attachments(self, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        搜尋包含星展銀行帳單且含有 PDF 附件的信件
        回傳附件檔案 byte 資料列表
        """
        creds = self.get_credentials()
        if not creds:
            raise ValueError("尚未授權 Google 帳號，請先登入授權")

        service = build('gmail', 'v1', credentials=creds)

        # 搜尋關鍵字：星展銀行 帳單 並且帶有 PDF 附件
        query = 'has:attachment filename:pdf (星展 OR DBS OR "星展銀行" OR "星展(台灣)商業銀行") (帳單 OR eStatement OR "信用卡電子帳單")'
        
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get('messages', [])
        attachments_found = []

        for msg_summary in messages:
            msg_id = msg_summary['id']
            msg = service.users().messages().get(userId='me', id=msg_id).execute()
            
            headers = msg.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '無主旨')
            date_received = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')

            # 走訪 payload 尋找 PDF 附件
            parts = msg.get('payload', {}).get('parts', [])
            for part in parts:
                filename = part.get('filename', '')
                if filename and filename.lower().endswith('.pdf'):
                    body = part.get('body', {})
                    att_id = body.get('attachmentId')
                    
                    if att_id:
                        att = service.users().messages().attachments().get(
                            userId='me', messageId=msg_id, id=att_id
                        ).execute()
                        data = att.get('data')
                        file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))

                        attachments_found.append({
                            "message_id": msg_id,
                            "subject": subject,
                            "date_received": date_received,
                            "filename": filename,
                            "pdf_bytes": file_data
                        })

        return attachments_found

