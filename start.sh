#!/usr/bin/env bash

# Установка необходимых браузеров Playwright
echo "Installing Playwright browsers..."
playwright install --with-deps chromium

# Запуск вашего Python-скрипта
echo "Starting Discord bot..."
python3 main_bot.py