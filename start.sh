#!/usr/bin/env bash

echo "Installing Playwright browsers without system permissions..."

# НОВОЕ ИЗМЕНЕНИЕ: Используем флаг --with-deps и явно указываем место установки.
# Это обходит проблему с su/sudo.
playwright install --with-deps chromium --install-dir=/usr/local/bin

# Дополнительно: убеждаемся, что Playwright установил драйверы в нужную папку
export PLAYWRIGHT_BROWSERS_PATH=/usr/local/bin/ms-playwright/

echo "Starting Discord bot..."
python3 main_bot.py
