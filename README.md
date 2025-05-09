# SmartClass Connect Bot

SmartClass Connect is a Telegram bot designed to support elementary and KG schools in Ethiopia. It enhances communication, resource sharing, and tuition tracking by integrating with tools like Google Sheets and Drive.

## 📌 Features

- ✅ Student and Parent Registration Verification
- 📚 Access to Books and Class Resources
- 📢 Announcements from Teachers and Admins
- 💵 Tuition Fee Tracking and Reporting (via Google Sheets)
- 🔒 Admin Verification Panel
- 🎓 Designed for Ethiopian schools with a local context in mind

## ⚙️ Technologies Used

- **Python**
- **python-telegram-bot** (v20+)
- **Google Sheets API** via `gspread` and `oauth2client`
- **Render.com** for deployment
- **.env** file for secure token handling

## 🚀 Deployment Guide

1. Push your bot project to GitHub
2. Connect your repo to [Render.com](https://render.com)
3. Create a **Background Worker** service
4. Set the start command:
   ```bash
   python bot.py
