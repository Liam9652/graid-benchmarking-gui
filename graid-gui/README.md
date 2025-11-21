# GRAID Web GUI

基于 Web 的 GRAID 基准测试管理系统。

## 快速开始

```bash
# 1. 复制脚本文件
mkdir -p scripts
cp /path/to/graid-bench.sh scripts/
cp /path/to/bench.sh scripts/
cp /path/to/graid-bench.conf .

# 2. 启动应用
sudo docker-compose up -d

# 3. 打开浏览器
# http://localhost:3000
```

## 主要功能

- ⚙️ **配置管理** - Web UI 编辑 GRAID 参数
- 📊 **系统信息** - 显示硬件配置
- ▶️ **测试控制** - 启动/停止测试
- 💾 **结果管理** - 下载测试结果
- 📝 **日志查看** - 实时日志显示

## 常用命令

```bash
# 启动
sudo docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
sudo docker-compose down

# 进入容器
docker-compose exec backend bash
```

## 访问地址

- Web UI: http://localhost:3000
- API: http://localhost:5000
- 结果: ./results/
- 日志: ./logs/
