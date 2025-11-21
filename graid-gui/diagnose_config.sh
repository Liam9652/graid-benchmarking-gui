#!/bin/bash
# 快速診斷和修復 GRAID Backend 配置問題

echo "===== GRAID Backend 配置診斷 ====="
echo ""

# 1. 查找 backend 進程和工作目錄
echo "[1] 查找 backend 進程..."
BACKEND_PROC=$(ps aux | grep "[p]ython.*app.py" | head -1)
if [ -n "$BACKEND_PROC" ]; then
    echo "✓ Backend 進程運行中"
    BACKEND_PID=$(echo "$BACKEND_PROC" | awk '{print $2}')
    BACKEND_CWD=$(pwdx $BACKEND_PID 2>/dev/null | awk '{print $2}')
    echo "  PID: $BACKEND_PID"
    echo "  工作目錄: $BACKEND_CWD"
else
    echo "✗ Backend 進程未運行"
    BACKEND_CWD=$(pwd)
fi

echo ""

# 2. 查找 app.py 位置
echo "[2] 查找 app.py 文件..."
APP_PY=$(find /opt /home /root -name "app.py" -path "*/backend/*" 2>/dev/null | head -1)
if [ -n "$APP_PY" ]; then
    echo "✓ 找到 app.py: $APP_PY"
    APP_DIR=$(dirname "$APP_PY")
    BASE_DIR=$(dirname "$APP_DIR")
    EXPECTED_CONFIG="$BASE_DIR/graid-bench.conf"
    echo "  預期配置文件位置: $EXPECTED_CONFIG"
else
    echo "✗ 未找到 app.py"
    # 嘗試從工作目錄推測
    EXPECTED_CONFIG="$BACKEND_CWD/../graid-bench.conf"
fi

echo ""

# 3. 檢查配置文件
echo "[3] 檢查配置文件..."
if [ -f "$EXPECTED_CONFIG" ]; then
    echo "✓ 配置文件存在: $EXPECTED_CONFIG"
    LINE_COUNT=$(wc -l < "$EXPECTED_CONFIG")
    echo "  行數: $LINE_COUNT"
    
    # 測試解析
    echo "  測試解析前5個配置項:"
    grep -E "^[A-Z_]+=.*$" "$EXPECTED_CONFIG" | grep -v "^#" | head -5
else
    echo "✗ 配置文件不存在: $EXPECTED_CONFIG"
    
    # 查找其他可能的位置
    echo ""
    echo "  搜索其他可能的配置文件位置..."
    FOUND_CONFIGS=$(find /opt /home /root -name "graid-bench.conf" 2>/dev/null)
    if [ -n "$FOUND_CONFIGS" ]; then
        echo "  找到以下配置文件:"
        echo "$FOUND_CONFIGS"
    fi
fi

echo ""

# 4. 測試 API
echo "[4] 測試 Backend API..."
API_RESPONSE=$(curl -s http://localhost:5000/api/config 2>/dev/null)
if [ -n "$API_RESPONSE" ]; then
    echo "✓ API 響應:"
    echo "$API_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$API_RESPONSE"
    
    # 檢查是否為空
    if echo "$API_RESPONSE" | grep -q '"data":{}'; then
        echo ""
        echo "⚠ 警告: API 返回空配置！"
    fi
else
    echo "✗ API 無響應（檢查 backend 是否在 5000 端口運行）"
fi

echo ""
echo "===== 診斷完成 ====="
echo ""

# 5. 提供修復建議
if [ ! -f "$EXPECTED_CONFIG" ]; then
    echo "建議操作:"
    echo "1. 將 graid-bench.conf 複製到: $EXPECTED_CONFIG"
    echo "   命令: cp graid-bench.conf $EXPECTED_CONFIG"
    echo ""
fi

if echo "$API_RESPONSE" | grep -q '"data":{}' 2>/dev/null; then
    echo "建議操作:"
    echo "1. 修復 app.py 中的 ConfigManager.load_config() 方法"
    echo "2. 使用提供的修復補丁"
    echo "3. 重啟 backend 服務"
    echo ""
fi

# 6. 提供一鍵修復選項
echo "是否執行自動修復? (y/N): "
read -r CONFIRM

if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
    echo ""
    echo "執行自動修復..."
    
    # 複製配置文件
    if [ ! -f "$EXPECTED_CONFIG" ] && [ -f "graid-bench.conf" ]; then
        echo "複製配置文件..."
        cp graid-bench.conf "$EXPECTED_CONFIG"
        echo "✓ 配置文件已複製"
    fi
    
    echo ""
    echo "請手動應用 ConfigManager 補丁並重啟 backend"
fi