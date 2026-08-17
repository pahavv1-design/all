import os

# Переменные из хостинга (безопасно!)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CHECKLIST_TIME = os.getenv("CHECKLIST_TIME", "09:00")
