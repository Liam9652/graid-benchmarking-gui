import React from 'react';

const PrintReport = ({ comparisonData, systemInfo, reportImages }) => {
    if (!comparisonData || !comparisonData.graid) return null;

    const today = new Date().toISOString().split('T')[0];

    // Extract RAID info from first graid data point if available
    const firstGraid = comparisonData.graid[0] || {};
    const raidType = firstGraid.RAID_type || 'N/A';
    const driveCount = firstGraid.PD_count || 'N/A';

    // Group images for visual representation
    const sortedImages = [...reportImages].sort((a, b) => {
        // Sort by RAID status (Normal first) then by workload
        if (a.tags.status === 'Normal' && b.tags.status !== 'Normal') return -1;
        if (a.tags.status !== 'Normal' && b.tags.status === 'Normal') return 1;
        return a.name.localeCompare(b.name);
    });

    return (
        <div className="print-report-container" id="printable-report">
            <header className="print-header">
                <h1>SupremeRAID Performance Test Report</h1>
            </header>

            <section className="print-section">
                <h2>1. 測試概述 (Executive Summary)</h2>
                <ul>
                    <li><strong>測試日期：</strong> {today}</li>
                    <li><strong>測試人員：</strong> [姓名/部門]</li>
                    <li><strong>測試目的：</strong> 評估 SupremeRAID {systemInfo.controller_info?.[0]?.Name || '[型號]'} 在特定硬體配置下的性能表現，並驗證其對 NVMe SSD 的加速能力。</li>
                    <li><strong>總結：</strong> [請在此填寫測試摘要]</li>
                </ul>
            </section>

            <section className="print-section">
                <h2>2. 測試環境 (Test Environment)</h2>
                <h3>2.1 硬體配置項目詳細規格</h3>
                <table className="print-table">
                    <thead>
                        <tr>
                            <th>Item</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td>Server</td><td>[Server Model]</td></tr>
                        <tr><td>CPU</td><td>[CPU Specs]</td></tr>
                        <tr><td>MEM</td><td>[Memory Specs]</td></tr>
                        <tr><td>RAID</td><td>SupremeRAID™ {systemInfo.controller_info?.[0]?.Name || '[型號]'}</td></tr>
                        <tr><td>Driver Version</td><td>{systemInfo.graid_version || 'N/A'}</td></tr>
                        <tr><td>NVMe SSD</td><td>{systemInfo.nvme_info?.[0]?.Model || 'N/A'} x {systemInfo.nvme_info?.length || 0}</td></tr>
                        <tr><td>OS</td><td>{systemInfo.os_info || 'N/A'} (Kernel {systemInfo.kernel_version || 'N/A'})</td></tr>
                        <tr><td>FIO</td><td>{firstGraid['fio-version'] || 'fio'}</td></tr>
                    </tbody>
                </table>

                <h3>2.2 RAID 配置</h3>
                <table className="print-table">
                    <thead>
                        <tr>
                            <th>Item</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td>RAID Type</td><td>{raidType}</td></tr>
                        <tr><td>PD Count</td><td>{driveCount}</td></tr>
                        <tr><td>DG Num</td><td>1</td></tr>
                        <tr><td>VD Num</td><td>1</td></tr>
                    </tbody>
                </table>

                <h3>2.3 測試工具與參數 (Testing Methodology)</h3>
                <table className="print-table">
                    <thead>
                        <tr>
                            <th>Item</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr><td>Tool</td><td>fio</td></tr>
                        <tr><td>IO Depth (QD)</td><td>{firstGraid.QD || '64'}</td></tr>
                        <tr><td>NumJobs</td><td>{firstGraid.jobs || '64'}</td></tr>
                        <tr><td>Runtime</td><td>{firstGraid.runtime || '180'}s</td></tr>
                        <tr><td>Stage</td><td>AfterDiscard / AfterPrecondition</td></tr>
                    </tbody>
                </table>
            </section>

            <section className="print-section">
                <h2>3. 吞吐量與 IOPS (Throughput & IOPS)</h2>
                <table className="print-table performance-table">
                    <thead>
                        <tr>
                            <th>測試模式 (Workload)</th>
                            <th>區塊大小 (Block Size)</th>
                            <th>IOPS (K)</th>
                            <th>吞吐量 (GB/s)</th>
                            <th>平均延遲 (Avg Latency)</th>
                            <th>CPU 使用率 (%)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {comparisonData.graid.filter(d =>
                            ['4k Random Read', '4k Random Write', '1M Sequential Read', '1M Sequential Write', '4k Random Read/Write Mix(70/30)'].includes(d.Workload)
                        ).map((d, i) => (
                            <tr key={i}>
                                <td>{d.Workload}</td>
                                <td>{d.Workload.includes('4k') ? '4KB' : '1MB'}</td>
                                <td>{d['IOPS(K)']}</td>
                                <td>{d['Bandwidth (GB/s)']}</td>
                                <td>{d['Avg Latency']}</td>
                                <td>{d.CPU_total || '-'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>

            <section className="print-section">
                <h2>4. 降級與重建測試 (Degraded & Rebuild Mode) - 選填</h2>
                <p>評估當一顆 SSD 損壞時的性能影響。</p>
                <ul>
                    <li><strong>Degraded Mode 性能：</strong> [數據/百分比]</li>
                    <li><strong>Rebuild 速度：</strong> [GB/hr 或完成時間]</li>
                    <li><strong>重建期間應用影響：</strong> [如果有]</li>
                </ul>
            </section>

            <section className="print-section page-break-before">
                <h2>5. 性能對比圖表 (Visual Representation)</h2>
                <div className="print-gallery">
                    {sortedImages.map((img, idx) => (
                        <div key={idx} className="print-gallery-item">
                            <img src={img.url} alt={img.name} />
                            <div className="img-caption">{img.tags.raid} {img.tags.status} - {img.tags.workload} ({img.tags.bs})</div>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    );
};

export default PrintReport;
