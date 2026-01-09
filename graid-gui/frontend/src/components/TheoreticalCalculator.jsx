
import React, { useState } from 'react';
import { calculatePerformance, RAID_TYPES, CARD_LIMITS } from '../utils/perfCalculator';
import './TheoreticalCalculator.css'; // We'll create this CSS next
import HelpButton from './HelpButton';
import { helpContent } from '../utils/helpContent';

const TheoreticalCalculator = ({ language }) => {
    // State for inputs
    const [numDrives, setNumDrives] = useState(12);

    // Default values matched with the original HTML
    const [inputs, setInputs] = useState({
        iopsRead4k: 1000000, // 1M
        iopsWrite4k: 600000, // 600k
        iopsMixed4k: 400000, // 400k
        randRead64k: 5000,   // 5000 MB/s = 5 GB/s
        randWrite64k: 2000,  // 2000 MB/s = 2 GB/s
        platformBaselineIOPS: 20000000 // 20M
    });

    const [version, setVersion] = useState('1.7.x'); // '1.7.x' or '2.0'
    const [cardModel, setCardModel] = useState('SR1010');

    // Filter card models based on version
    const getVisibleModels = () => {
        const allModels = Object.keys(CARD_LIMITS);
        const v2OnlyModels = ['SR-PAM2', 'SR-UAD2', 'SR-CAM2'];

        if (version === '2.0') {
            return allModels;
        } else {
            return allModels.filter(m => !v2OnlyModels.includes(m));
        }
    };

    const handleVersionChange = (newVersion) => {
        setVersion(newVersion);
        if (newVersion === '1.7.x') {
            const v2OnlyModels = ['SR-PAM2', 'SR-UAD2', 'SR-CAM2'];
            if (v2OnlyModels.includes(cardModel)) {
                setCardModel('SR1010');
            }
        }
    };


    const handleChange = (e, key, multiplier = 1) => {
        setInputs(prev => ({
            ...prev,
            [key]: parseFloat(e.target.value) * multiplier
        }));
    };

    // Helper to handle unit changes separately from value (UI complexity)
    // To simplify, I'll implement the UI with unit separate from state storage 
    // or just assume standard input for now. 
    // Let's implement dynamic unit selection to match original UX.

    const [uiState, setUiState] = useState({
        iopsRead4kVal: 1, iopsRead4kUnit: 1000000,
        iopsWrite4kVal: 600, iopsWrite4kUnit: 1000,
        iopsMixed4kVal: 400, iopsMixed4kUnit: 1000,
        randRead64kVal: 5, randRead64kUnit: 1000, // Unit for BW input implies output in MB/s. 1000 = GB->MB? No, original had MB/s=1.
        // Original BW: option 1=MB/s. 
        randWrite64kVal: 2, randWrite64kUnit: 1000,
        platformBaselineVal: 20, platformBaselineUnit: 1000000
    });

    // Sync input object when UI state changes
    React.useEffect(() => {
        setInputs({
            iopsRead4k: uiState.iopsRead4kVal * uiState.iopsRead4kUnit,
            iopsWrite4k: uiState.iopsWrite4kVal * uiState.iopsWrite4kUnit,
            iopsMixed4k: uiState.iopsMixed4kVal * uiState.iopsMixed4kUnit,
            randRead64k: uiState.randRead64kVal * (uiState.randRead64kUnit === 1000 ? 1000 :
                uiState.randRead64kUnit === 1 ? 1 : 0.001),
            // Wait, BW logic in original: 
            // 0.001 -> kB/s (val * 0.001 = MB/s)
            // 1 -> MB/s (val * 1 = MB/s)
            // 1000 -> GB/s (val * 1000 = MB/s)

            randWrite64k: uiState.randWrite64kVal * (uiState.randWrite64kUnit === 1000 ? 1000 :
                uiState.randWrite64kUnit === 1 ? 1 : 0.001),

            platformBaselineIOPS: uiState.platformBaselineVal * uiState.platformBaselineUnit
        });
    }, [uiState]);

    const handleUiChange = (key, value) => {
        setUiState(prev => ({ ...prev, [key]: parseFloat(value) }));
    };

    // FIO Log Parsing
    const handleFileUpload = (e, type) => {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const json = JSON.parse(event.target.result);
                if (type === 'pd') {
                    parsePdFio(json);
                } else {
                    parseBaselineFio(json);
                }
            } catch (err) {
                alert("❌ Failed to parse JSON. Please ensure it is a valid FIO JSON output.");
            }
        };
        reader.readAsText(file);
    };

    const findJob = (jobs, name) => jobs.find(j => j.jobname.includes(name));

    const setIOPSField = (valKey, unitKey, value) => {
        let displayValue = value;
        let unit = 1000000; // Default M

        if (value >= 1_000_000_000) {
            displayValue = value / 1_000_000_000;
            unit = 1_000_000_000;
        } else if (value >= 1_000_000) {
            displayValue = value / 1_000_000;
            unit = 1_000_000;
        } else if (value >= 1_000) {
            displayValue = value / 1_000;
            unit = 1_000;
        }

        setUiState(prev => ({
            ...prev,
            [valKey]: parseFloat(displayValue.toFixed(1)),
            [unitKey]: unit
        }));
    };

    const setBWField = (valKey, unitKey, bwKB) => {
        let value = bwKB / 1000; // Convert to MB/s
        let unit = 1000; // Default GB/s target for selector if large enough

        if (value >= 1000) {
            value = value / 1000; // Display in GB/s
            unit = 1000;
        } else if (value >= 1) {
            unit = 1; // Display in MB/s
        } else {
            value = value * 1000; // Display in kB/s
            unit = 0.001; // Selector value for kB/s
        }

        setUiState(prev => ({
            ...prev,
            [valKey]: parseFloat(value.toFixed(1)),
            [unitKey]: unit
        }));
    };

    const parsePdFio = (json) => {
        const jobs = json.jobs;
        if (!jobs) return;

        const job4kRead = findJob(jobs, "4k_random_read");
        const job4kWrite = findJob(jobs, "4k_random_write");
        const job4kMixed = findJob(jobs, "4k_random_50read_50write");
        const job64kRead = findJob(jobs, "64k_random_read");
        const job64kWrite = findJob(jobs, "64k_random_write");

        if (job4kRead) setIOPSField("iopsRead4kVal", "iopsRead4kUnit", job4kRead.read.iops);
        if (job4kWrite) setIOPSField("iopsWrite4kVal", "iopsWrite4kUnit", job4kWrite.write.iops);
        if (job4kMixed) setIOPSField("iopsMixed4kVal", "iopsMixed4kUnit", job4kMixed.write.iops);
        if (job64kRead) setBWField("randRead64kVal", "randRead64kUnit", job64kRead.read.bw);
        if (job64kWrite) setBWField("randWrite64kVal", "randWrite64kUnit", job64kWrite.write.bw);

        alert("✅ PD Fio JSON parsed successfully.");
    };

    const parseBaselineFio = (json) => {
        try {
            const job = findJob(json.jobs, "nvme");
            if (!job || !job.read || typeof job.read.iops !== "number") throw new Error("read.iops not found");
            setIOPSField("platformBaselineVal", "platformBaselineUnit", job.read.iops);
            alert("✅ Platform baseline IOPS parsed successfully.");
        } catch (e) {
            alert("❌ Failed to extract baseline data.");
        }
    };

    const tableData = RAID_TYPES.map(raid => {
        const perf = calculatePerformance(raid, numDrives, {
            readIOPS: inputs.iopsRead4k,
            writeIOPS: inputs.iopsWrite4k,
            mixedIOPS: inputs.iopsMixed4k,
            readBW: inputs.randRead64k,
            writeBW: inputs.randWrite64k
        }, inputs.platformBaselineIOPS, version, cardModel);
        return { raid, ...perf };
    });

    return (
        <div className="calculator-container">
            <div className="calc-header-row">
                <h2>Theoretical Performance Calculator</h2>
                <div className="version-toggle">
                    <button
                        className={`toggle-btn ${version === '1.7.x' ? 'active' : ''}`}
                        onClick={() => handleVersionChange('1.7.x')}
                    >
                        Linux V1
                    </button>
                    <button
                        className={`toggle-btn ${version === '2.0' ? 'active' : ''}`}
                        onClick={() => handleVersionChange('2.0')}
                    >
                        Linux V2
                    </button>
                </div>
            </div>


            <div className="calc-inputs">
                <div className="input-group">
                    <label>Number of PDs (SSDs):</label>
                    <input type="number" value={numDrives} onChange={(e) => setNumDrives(parseInt(e.target.value))} />
                </div>

                <div className="input-group">
                    <label>Graid Card Model:</label>
                    <select value={cardModel} onChange={(e) => setCardModel(e.target.value)}>
                        {getVisibleModels().map(model => (
                            <option key={model} value={model}>{model}</option>
                        ))}
                    </select>
                </div>


                <div className="input-group">
                    <label>Single PD 4K Random Read IOPS:</label>
                    <input type="number" value={uiState.iopsRead4kVal} onChange={(e) => handleUiChange('iopsRead4kVal', e.target.value)} />
                    <select value={uiState.iopsRead4kUnit} onChange={(e) => handleUiChange('iopsRead4kUnit', e.target.value)}>
                        <option value="1000">k</option>
                        <option value="1000000">M</option>
                    </select>
                </div>

                <div className="input-group">
                    <label>Single PD 4K Random Write IOPS:</label>
                    <input type="number" value={uiState.iopsWrite4kVal} onChange={(e) => handleUiChange('iopsWrite4kVal', e.target.value)} />
                    <select value={uiState.iopsWrite4kUnit} onChange={(e) => handleUiChange('iopsWrite4kUnit', e.target.value)}>
                        <option value="1000">k</option>
                        <option value="1000000">M</option>
                    </select>
                </div>

                <div className="input-group">
                    <label>Single PD 4K 50/50 Mixed IOPS:</label>
                    <input type="number" value={uiState.iopsMixed4kVal} onChange={(e) => handleUiChange('iopsMixed4kVal', e.target.value)} />
                    <select value={uiState.iopsMixed4kUnit} onChange={(e) => handleUiChange('iopsMixed4kUnit', e.target.value)}>
                        <option value="1000">k</option>
                        <option value="1000000">M</option>
                    </select>
                </div>

                <div className="input-group">
                    <label>Single PD 64K Random Read Throughput:</label>
                    <input type="number" value={uiState.randRead64kVal} onChange={(e) => handleUiChange('randRead64kVal', e.target.value)} />
                    <select value={uiState.randRead64kUnit} onChange={(e) => handleUiChange('randRead64kUnit', e.target.value)}>
                        <option value="0.001">kB/s</option>
                        <option value="1">MB/s</option>
                        <option value="1000">GB/s</option>
                    </select>
                </div>

                <div className="input-group">
                    <label>Single PD 64K Random Write Throughput:</label>
                    <input type="number" value={uiState.randWrite64kVal} onChange={(e) => handleUiChange('randWrite64kVal', e.target.value)} />
                    <select value={uiState.randWrite64kUnit} onChange={(e) => handleUiChange('randWrite64kUnit', e.target.value)}>
                        <option value="0.001">kB/s</option>
                        <option value="1">MB/s</option>
                        <option value="1000">GB/s</option>
                    </select>
                </div>

                <div className="input-group">
                    <label>Platform Baseline 4K Random Read IOPS:</label>
                    <input type="number" value={uiState.platformBaselineVal} onChange={(e) => handleUiChange('platformBaselineVal', e.target.value)} />
                    <select value={uiState.platformBaselineUnit} onChange={(e) => handleUiChange('platformBaselineUnit', e.target.value)}>
                        <option value="1000">k</option>
                        <option value="1000000">M</option>
                        <option value="1000000000">B</option>
                    </select>
                </div>

                <hr style={{ margin: '20px 0', borderColor: '#444' }} />

                <div className="file-upload-section" style={{ display: 'flex', gap: '20px' }}>
                    <div className="input-group">
                        <label>Upload single PD FIO test log:</label>
                        <input type="file" accept=".json,.log,.txt" onChange={(e) => handleFileUpload(e, 'pd')} />
                    </div>
                    <div className="input-group">
                        <label>Upload platform baseline FIO log:</label>
                        <input type="file" accept=".json,.log,.txt" onChange={(e) => handleFileUpload(e, 'baseline')} />
                    </div>
                </div>
            </div>

            <div className="calc-output">
                <table>
                    <thead>
                        <tr>
                            <th>RAID Type</th>
                            <th>Workload</th>
                            <th>Performance</th>
                            <th>Calculation or Note</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tableData.map((data) => (
                            <React.Fragment key={data.raid}>
                                <tr>
                                    <td rowSpan="4" className="raid-type-cell">{data.raid}</td>
                                    <td>4K Random Read</td>
                                    <td>{data.readIOPS}</td>
                                    <td>{data.notes.readIOPS}</td>
                                </tr>
                                <tr>
                                    <td>4K Random Write</td>
                                    <td>{data.writeIOPS}</td>
                                    <td>{data.notes.writeIOPS}</td>
                                </tr>
                                <tr>
                                    <td>1M Sequential Read</td>
                                    <td>{data.readBW}</td>
                                    <td>{data.notes.readBW}</td>
                                </tr>
                                <tr>
                                    <td>1M Sequential Write</td>
                                    <td>{data.writeBW}</td>
                                    <td>{data.notes.writeBW}</td>
                                </tr>
                            </React.Fragment>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default TheoreticalCalculator;
