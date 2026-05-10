import os

import datetime
import logging
from typing import Optional

logger = logging.getLogger("J.A.R.V.I.S")

# Scopes specify the level of access.
SCOPES = ['https://www.googleapis.com/auth/calendar']

class CalendarService:
    def __init__(self):
        self.creds = None
        self._init_oauth()

    def _init_oauth(self):
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
        except ImportError:
            logger.warning("[CALENDAR] google-api-python-client not installed.")
            return

        token_file = 'token.json'
        credentials_file = 'credentials.json'

        # Load existing tokens if they exist
        if os.path.exists(token_file):
            self.creds = Credentials.from_authorized_user_file(token_file, SCOPES)

        # If no valid credentials, let the user log in
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception as e:
                    logger.warning("[CALENDAR] Auto-refresh failed: %s", e)
                    self.creds = None

            if not self.creds:
                if not os.path.exists(credentials_file):
                    logger.warning(f"[CALENDAR] '{credentials_file}' not found. Google Calendar features disabled.")
                    return
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                    # This will open the browser and block until auth completes
                    self.creds = flow.run_local_server(port=0)
                except Exception as e:
                    logger.error("[CALENDAR] OAuth flow failed: %s", e)
                    return

            # Save the credentials for the next run
            with open(token_file, 'w') as token:
                token.write(self.creds.to_json())

        logger.info("[CALENDAR] Google Calendar authentication successful.")

    def get_todays_agenda(self) -> dict:
        if not self.creds:
            return {"error": "Google Calendar is not configured. Missing credentials.json."}
            
        try:
            from googleapiclient.discovery import build
            service = build('calendar', 'v3', credentials=self.creds)
            
            now = datetime.datetime.utcnow().isoformat() + 'Z'
            end_of_day = (datetime.datetime.utcnow().replace(hour=23, minute=59, second=59)).isoformat() + 'Z'
            
            events_result = service.events().list(calendarId='primary', timeMin=now, timeMax=end_of_day,
                                                  maxResults=10, singleEvents=True,
                                                  orderBy='startTime').execute()
            items = events_result.get('items', [])
            
            if not items:
                return {"title": "Today's Agenda", "events": []}
                
            structured_events = []
            for item in items:
                start = item['start'].get('dateTime', item['start'].get('date'))
                time_str = start.split('T')[1][:5] if 'T' in start else "All day"
                structured_events.append({
                    "start": time_str,
                    "summary": item.get('summary', 'No Title'),
                    "location": item.get('location', '')
                })
                
            return {
                "title": "Today's Agenda",
                "events": structured_events
            }
        except Exception as e:
            logger.error("[CALENDAR] Failed to retrieve agenda: %s", e)
            return {"error": f"Failed to retrieve agenda: {e}"}

    def schedule_event(self, title: str, start_time: str, end_time: str) -> str:
        """
        start_time/end_time should be ISO 8601 formatted strings (e.g. 2026-04-23T15:00:00-07:00)
        """
        if not self.creds:
            return "Google Calendar is not configured. Missing credentials.json."
            
        try:
            from googleapiclient.discovery import build
            service = build('calendar', 'v3', credentials=self.creds)
            
            event = {
              'summary': title,
              'start': {
                'dateTime': start_time,
                'timeZone': 'UTC',
              },
              'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',
              },
            }
            
            event_result = service.events().insert(calendarId='primary', body=event).execute()
            return f"Event '{title}' created successfully: {event_result.get('htmlLink')}"
        except Exception as e:
            logger.error("[CALENDAR] Failed to schedule event: %s", e)
            return f"Failed to schedule event: {e}"
