#!/bin/bash

# Setup script for YandexGPT integration

echo "🚀 Setting up YandexGPT integration..."
echo ""

# Check if .env exists
if [ -f ".env" ]; then
    echo "✅ .env file already exists"
else
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "✅ .env file created"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env file and add your Yandex Cloud credentials:"
    echo "   - YANDEX_API_KEY"
    echo "   - YANDEX_FOLDER_ID"
    echo ""
fi

# Install dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo "✅ Dependencies installed successfully"
else
    echo "❌ Failed to install dependencies"
    exit 1
fi

echo ""
echo "✨ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your Yandex Cloud credentials"
echo "2. Run your bot as usual"
echo ""
echo "📖 For detailed instructions, see: YANDEX_GPT_GUIDE.md"
