#!/usr/bin/env bash

echo "Installing Playwright browsers without system permissions..."

# Используем флаг --install-dir=/usr/local/bin, чтобы избежать проблем с su/sudo.
playwright install --with-deps chromium --install-dir=/usr/local/bin

# Экспортируем путь к браузерам для Python-кода
export PLAYWRIGHT_BROWSERS_PATH=/usr/local/bin/ms-playwright/

# Скрипт завершается. Запуск бота берет на себя Start Command Render
