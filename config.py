import os
import sys

# Проверяем, что переменные установлены
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
CHECKLIST_TIME = os.getenv("CHECKLIST_TIME", "09:00")

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не установлен!")
    sys.exit(1)

if not ADMIN_ID:
    print("❌ ОШИБКА: ADMIN_ID не установлен!")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    print(f"❌ ОШИБКА: ADMIN_ID должен быть числом, а не {ADMIN_ID}")
    sys.exit(1)

print(f"✅ BOT_TOKEN: {BOT_TOKEN[:10]}... (скрыто)")
print(f"✅ ADMIN_ID: {ADMIN_ID}")
print(f"✅ CHECKLIST_TIME: {CHECKLIST_TIME}")
