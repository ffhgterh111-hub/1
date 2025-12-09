#!/usr/bin/env bash

# Установка системных зависимостей для Chromium/Playwright
# Этот шаг может быть не нужен на Render, если они уже предустановлены, 
# но это гарантирует успех.
# Render часто использует Debian, поэтому используем apt.
# В более новых версиях Render могут быть другие механизмы.

# Установка бинарников Chromium для Playwright
playwright install chromium

# Запуск вашего Python-бота
python main_bot.py
