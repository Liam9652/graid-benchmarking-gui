export const helpContent = {
    ZH: {
        config: {
            title: "配置管理說明",
            sections: [
                { header: "NVMe 設備選擇", content: "從列表中選擇要用於測試的 NVMe 設備。請注意授權限制（License Limit）。" },
                { header: "RAID 類型選擇", content: "您可以選擇多個 RAID 級別。系統將針對每個選定的級別運行單獨的測試。" },
                { header: "高級選項", content: "設置測試階段以及運行時間等高級參數。" },
                { header: "遠端測試機設定", content: "配置遠端 DUT 連接。請確保使用具備 root 權限的帳號。若非 root 使用者，系統將嘗試使用提供的 SSH 密碼透過 sudo 執行硬體指令。測試前需點擊『Connect』驗證權限並獲取設備資訊。" },
                { header: "操作提示", content: "修改配置後，請務必點擊『Save Configuration』以保存更改。點擊『Reset』可清除現有的 Graid 資源（VD/DG/PD）。" }
            ]
        },
        benchmark: {
            title: "測試控制板說明",
            sections: [
                { header: "啟動測試", content: "點擊『Start Benchmark』開始運行測試。測試過程中將顯示實時狀態和進度。" },
                { header: "實時監控", content: "提供三種視圖：\n- Chart View: 顯示 IOPS、帶寬和延遲的趨勢圖。\n- Report View: 提供數值化報告。\n- Audit Log: 顯示後台詳細的運行日誌。" },
                { header: "停止測試", content: "點擊『Stop Benchmark』可隨時中斷當前正在運行的測試。" }
            ]
        },
        results: {
            title: "測試結果說明",
            sections: [
                { header: "結案對比", content: "選擇一個歷史測試。點擊『Generate Comparison』來載入數據。您可以選中 Baseline 與 SupremeRAID 進行性能對比。" },
                { header: "Dashboard 視圖", content: "直觀顯示各個工作負載（Workload）下的性能差異。" },
                { header: "Gallery 視圖", content: "查看測試過程中自動捕獲的性能報告截圖。您可以通過 RAID、狀態或類型進行細化過濾。" }
            ]
        },
        calculator: {
            title: "理論性能計算機說明",
            sections: [
                { header: "參數設置", content: "選擇 SupremeRAID 卡型號、磁碟型號、數量以及 RAID 級別。" },
                { header: "系統配置", content: "填入 CPU 核心數與每顆 CPU 的 RAM 數量。核心數會影響隨機 IO (IOPs) 上限，而 RAM 數量與 DDR 類型則會決定系統頻寬上限。" },
                { header: "計算邏輯", content: "系統將根據硬體規格和 RAID 公式計算理論上的性能上限（IOPS 與帶寬）。" },
                { header: "參考價值", content: "該數值僅供理論參考，代表硬體在理想狀態下的極限性能。實際測試結果可能會受系統配置、驅動及工作負載影響。" }
            ]
        }
    },
    CN: {
        config: {
            title: "配置管理说明",
            sections: [
                { header: "NVMe 设备选择", content: "从列表中选择要用于测试的 NVMe 设备。请注意授权限制（License Limit）。" },
                { header: "RAID 类型选择", content: "您可以选择多个 RAID 级别。系统将针对每个选定的级别运行单独的测试。" },
                { header: "高级选项", content: "设置测试阶段以及运行时间等高级参数。" },
                { header: "远端测试机设定", content: "配置远端 DUT 连接。请确保使用具备 root 权限的账号。若非 root 用户，系统将尝试使用提供的 SSH 密码通过 sudo 执行硬件指令。测试前需点击『Connect』验证权限并获取设备信息。" },
                { header: "操作提示", content: "修改配置后，请务必点击『Save Configuration』以保存更改。点击『Reset』可清除现有的 Graid 资源（VD/DG/PD）。" }
            ]
        },
        benchmark: {
            title: "测试控制板说明",
            sections: [
                { header: "启动测试", content: "点击『Start Benchmark』开始运行测试。测试过程中将显示实时状态和进度。" },
                { header: "实时监控", content: "提供三种视图：\n- Chart View: 显示 IOPS、带宽和延迟的趋势图。\n- Report View: 提供数值化报告。\n- Audit Log: 显示后台详细的运行日志。" },
                { header: "停止测试", content: "点击『Stop Benchmark』可随时中断当前正在运行的测试。" }
            ]
        },
        results: {
            title: "测试结果说明",
            sections: [
                { header: "结果对比", content: "选择一个历史测试。点击『Generate Comparison』来加载数据。您可以选中 Baseline 与 SupremeRAID 进行性能对比。" },
                { header: "Dashboard 视图", content: "直观显示各个工作负载（Workload）下的性能差异。" },
                { header: "Gallery 视图", content: "查看测试过程中自动捕获的性能报告截图。您可以通过 RAID、状态或类型进行细化过滤。" }
            ]
        },
        calculator: {
            title: "理论性能计算机说明",
            sections: [
                { header: "参数设置", content: "选择 SupremeRAID 卡型号、磁盘型号、数量以及 RAID 级别。" },
                { header: "系统配置", content: "填入 CPU 核心数与每颗 CPU 的 RAM 数量。核心数会影响随机 IO (IOPs) 上限，而 RAM 数量与 DDR 类型则会决定系统带宽上限。" },
                { header: "计算逻辑", content: "系统将根据硬件规格和 RAID 公式计算理论上的性能上限（IOPS 与带宽）。" },
                { header: "参考价值", content: "该数值仅供理论参考，代表硬件在理想状态下的极限性能。实际测试结果可能会受系统配置、驱动及工作负载影响。" }
            ]
        }
    },
    EN: {
        config: {
            title: "Configuration Management Help",
            sections: [
                { header: "NVMe Device Selection", content: "Select NVMe devices from the list for testing. Please note the License Limit." },
                { header: "RAID Type Selection", content: "You can select multiple RAID levels. The system will run individual tests for each selected level." },
                { header: "Advanced Options", content: "Set advanced parameters such as test stages and run time." },
                { header: "Remote DUT Setup", content: "Configure remote DUT connection. Ensure you use an account with root privileges. If not root, the system will attempt to use the provided SSH password for sudo. Click 'Connect' to verify and fetch info." },
                { header: "Operational Tips", content: "After modifying the configuration, be sure to click 'Save Configuration'. Click 'Reset' to clear existing Graid resources (VD/DG/PD)." }
            ]
        },
        benchmark: {
            title: "Benchmarking Control Board Help",
            sections: [
                { header: "Start Test", content: "Click 'Start Benchmark' to begin testing. Real-time status and progress will be displayed during the run." },
                { header: "Real-time Monitoring", content: "Three views are provided:\n- Chart View: Displays trends for IOPS, Bandwidth, and Latency.\n- Report View: Provides numerical reports.\n- Audit Log: Displays detailed background logs." },
                { header: "Stop Test", content: "Click 'Stop Benchmark' to interrupt the currently running test at any time." }
            ]
        },
        results: {
            title: "Test Results Help",
            sections: [
                { header: "Result Comparison", content: "Select a historical test. Click 'Generate Comparison' to load data. You can compare Baseline vs SupremeRAID performance." },
                { header: "Dashboard View", content: "Visually shows performance differences under various workloads." },
                { header: "Gallery View", content: "View performance report screenshots captured during the test. Filter by RAID, status, or type." }
            ]
        },
        calculator: {
            title: "Theoretical Performance Calculator Help",
            sections: [
                { header: "Parameter Settings", content: "Select SupremeRAID card model, drive model, count, and RAID level." },
                { header: "System Configuration", content: "Enter CPU core count and RAM per CPU. CPU cores impact Random IO (IOPs) limits, while RAM count and DDR type determine the system bandwidth ceiling." },
                { header: "Calculation Logic", content: "The system calculates theoretical performance limits (IOPS and Bandwidth) based on hardware specs and RAID formulas." },
                { header: "Reference Value", content: "These values are for theoretical reference only, representing limits in ideal conditions. Real-world results may vary." }
            ]
        }
    }
};
