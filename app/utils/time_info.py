from datetime import datetime

def get_time_information() -> str:
    now = datetime.now()
    return now.strftime("%A, %d %B %Y, %I:%M %p")