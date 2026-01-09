
// Logic extracted from GRAID Performance Calculator.html

export const RAID_TYPES = ['RAID0', 'RAID1', 'RAID5', 'RAID6', 'RAID10', 'SR-CRAID', 'SingleTest'];

export const CARD_LIMITS = {
    'SR1001': { randReadIOPS: 6_000_000, randWriteIOPS: { RAID5: 500_000, RAID6: 400_000 } },
    'SR1000': { randReadIOPS: 16_000_000, randWriteIOPS: { RAID5: 820_000, RAID6: 500_000 } },
    'SR1010': { randReadIOPS: 22_000_000, randWriteIOPS: { RAID5: 2_000_000, RAID6: 1_500_000 } },
    'SR-CAM2': {
        RAID5: { randReadIOPS: 10_000_000, randWriteIOPS: 2_900_000, seqReadBW: 140_000, seqWriteBW: 65_000 },
        RAID6: { randReadIOPS: 10_000_000, randWriteIOPS: 2_300_000, seqReadBW: 140_000, seqWriteBW: 60_000 },
        RAID10: { randReadIOPS: 10_000_000, randWriteIOPS: 6_000_000, seqReadBW: 140_000, seqWriteBW: 40_000 },
    },
    'SR-PAM2': {
        RAID5: { randReadIOPS: 22_000_000, randWriteIOPS: 5_000_000, seqReadBW: 280_000, seqWriteBW: 125_000 },
        RAID6: { randReadIOPS: 22_000_000, randWriteIOPS: 4_500_000, seqReadBW: 280_000, seqWriteBW: 120_000 },
        RAID10: { randReadIOPS: 18_000_000, randWriteIOPS: 10_000_000, seqReadBW: 280_000, seqWriteBW: 80_000 },
    },
    'SR-UAD2': {
        RAID5: { randReadIOPS: 30_000_000, randWriteIOPS: 6_000_000, seqReadBW: 280_000, seqWriteBW: 125_000 },
        RAID6: { randReadIOPS: 30_000_000, randWriteIOPS: 5_000_000, seqReadBW: 280_000, seqWriteBW: 120_000 },
        RAID10: { randReadIOPS: 22_000_000, randWriteIOPS: 11_000_000, seqReadBW: 280_000, seqWriteBW: 80_000 },
    }
};

/**
 * Calculates theoretical performance based on RAID level, drive count, and single PD metrics.
 */
export const calculatePerformance = (raidType, numDrives, pdMetrics, baselineIOPS = Infinity, version = '1.7.x', cardModel = 'SR1010') => {
    const { readIOPS, writeIOPS, mixedIOPS, readBW, writeBW } = pdMetrics;

    let result = {
        readIOPS: "0",
        writeIOPS: "0",
        readBW: "0",
        writeBW: "0",
        readIOPSVal: 0,
        writeIOPSVal: 0,
        readBWVal: 0,
        writeBWVal: 0,
        notes: {}
    };

    // Normalize RAID Type
    const normalizedRaidType = (raidType || '').toUpperCase().replace('-', '');
    let effectiveRaidType = normalizedRaidType;
    if (normalizedRaidType === 'SRCRAID') effectiveRaidType = 'RAID5';
    if (normalizedRaidType === 'SINGLETEST') effectiveRaidType = 'RAID0';

    // 1. Calculate Theoretical Max (Drive Bound)
    const rawReadIOPS = readIOPS * numDrives;
    const rawReadBW = readBW * numDrives;

    let rawWriteIOPS = 0;
    let rawWriteBW = 0;

    switch (effectiveRaidType) {
        case 'RAID0':
            rawWriteIOPS = writeIOPS * numDrives;
            rawWriteBW = writeBW * numDrives;
            result.notes.writeIOPS = `${formatIOPS(writeIOPS)} x ${numDrives}`;
            result.notes.writeBW = `${formatThroughput(writeBW)} x ${numDrives} (Typically higher)`;
            result.notes.readBW = `${formatThroughput(readBW)} x ${numDrives} (Typically higher)`;
            break;
        case 'RAID1':
            rawWriteIOPS = writeIOPS;
            rawWriteBW = writeBW;
            result.notes.writeIOPS = `${formatIOPS(writeIOPS)} x 1`;
            result.notes.writeBW = `${formatThroughput(writeBW)} x 1`;
            result.notes.readBW = `${formatThroughput(readBW)} x ${numDrives}`;
            break;
        case 'RAID10':
            rawWriteIOPS = (writeIOPS * numDrives) / 2;
            rawWriteBW = (writeBW * numDrives) / 2;
            result.notes.writeIOPS = `${formatIOPS(writeIOPS)} x ${numDrives} / 2`;
            result.notes.writeBW = `${formatThroughput(writeBW)} x ${numDrives} / 2`;
            result.notes.readBW = `${formatThroughput(readBW)} x ${numDrives}`;
            break;
        case 'RAID5':
            if (version === '2.0') {
                rawWriteIOPS = ((rawReadIOPS) / 4) * 0.9; // Base on theoretical read
                result.notes.writeIOPS = `(RAID5 random read) / 4 * 0.9 (v2.0 formula)`;
            } else {
                rawWriteIOPS = (mixedIOPS * numDrives) / 2;
                result.notes.writeIOPS = `${formatIOPS(mixedIOPS)} x ${numDrives} / 2`;
            }
            rawWriteBW = writeBW * (numDrives - 1) * 0.9;
            result.notes.writeBW = `${formatThroughput(writeBW)} x (${numDrives} - 1) * 0.9`;
            result.notes.readBW = `${formatThroughput(readBW)} x ${numDrives}`;
            break;
        case 'RAID6':
            if (version === '2.0') {
                rawWriteIOPS = ((rawReadIOPS) / 6) * 0.9; // Base on theoretical read
                result.notes.writeIOPS = `(RAID5 random read) / 6 * 0.9 (v2.0 formula)`;
            } else {
                rawWriteIOPS = (mixedIOPS * numDrives) / 3;
                result.notes.writeIOPS = `${formatIOPS(mixedIOPS)} x ${numDrives} / 3`;
            }
            rawWriteBW = writeBW * (numDrives - 2) * 0.9;
            result.notes.writeBW = `${formatThroughput(writeBW)} x (${numDrives} - 2) * 0.9`;
            result.notes.readBW = `${formatThroughput(readBW)} x ${numDrives}`;
            break;
    }

    // 2. Apply Capping (Platform Baseline & Card Spec)
    let finalReadIOPS = Math.min(rawReadIOPS, baselineIOPS);
    let finalWriteIOPS = rawWriteIOPS;
    let finalReadBW = rawReadBW;
    let finalWriteBW = rawWriteBW;

    const cardLimit = CARD_LIMITS[cardModel];
    const raidLimit = cardLimit?.[effectiveRaidType];

    if (raidLimit) {
        // V2 Style limits (RAID specific)
        if (finalReadIOPS > raidLimit.randReadIOPS) {
            finalReadIOPS = raidLimit.randReadIOPS;
            result.notes.readIOPS = `Capped by card spec (${cardModel})`;
        } else {
            result.notes.readIOPS = rawReadIOPS > baselineIOPS
                ? `Capped by platform baseline: ${formatIOPS(baselineIOPS)}`
                : `${formatIOPS(readIOPS)} x ${numDrives} = ${formatIOPS(rawReadIOPS)}`;
        }

        if (finalWriteIOPS > raidLimit.randWriteIOPS) {
            finalWriteIOPS = raidLimit.randWriteIOPS;
            result.notes.writeIOPS = `Capped by card spec (${cardModel})`;
        }

        if (finalReadBW > raidLimit.seqReadBW) {
            finalReadBW = raidLimit.seqReadBW;
            result.notes.readBW = `Capped by card spec (${cardModel})`;
        }

        if (finalWriteBW > raidLimit.seqWriteBW) {
            finalWriteBW = raidLimit.seqWriteBW;
            result.notes.writeBW = `Capped by card spec (${cardModel})`;
        }
    } else {
        // V1 Style limits (Generic read limit + RAID 5/6 write limit)
        if (finalReadIOPS > baselineIOPS) {
            result.notes.readIOPS = `Capped by platform baseline: ${formatIOPS(baselineIOPS)}`;
        } else {
            result.notes.readIOPS = `${formatIOPS(readIOPS)} x ${numDrives} = ${formatIOPS(rawReadIOPS)}`;
        }

        if (effectiveRaidType === 'RAID5' || effectiveRaidType === 'RAID6') {
            const cardReadLimit = CARD_LIMITS[cardModel]?.randReadIOPS;
            if (cardReadLimit && finalReadIOPS > cardReadLimit) {
                finalReadIOPS = cardReadLimit;
                result.notes.readIOPS = `Capped by card spec (${cardModel}): ${formatIOPS(cardReadLimit)}`;
            }

            const cardWriteLimit = CARD_LIMITS[cardModel]?.randWriteIOPS?.[effectiveRaidType];
            if (cardWriteLimit && finalWriteIOPS > cardWriteLimit) {
                finalWriteIOPS = cardWriteLimit;
                result.notes.writeIOPS = `Capped by card spec (${cardModel}): ${formatIOPS(cardWriteLimit)}`;
            }
        }
    }

    result.readIOPSVal = finalReadIOPS;
    result.writeIOPSVal = finalWriteIOPS;
    result.readBWVal = finalReadBW;
    result.writeBWVal = finalWriteBW;

    // Formatting strings
    result.readIOPS = formatIOPS(result.readIOPSVal);
    result.writeIOPS = formatIOPS(result.writeIOPSVal);
    result.readBW = formatThroughput(result.readBWVal);
    result.writeBW = formatThroughput(result.writeBWVal);

    return result;
};

// Formatting utilities
export const trimDecimal = (value) => {
    const fixed = value.toFixed(1);
    return fixed.endsWith('.0') ? parseInt(fixed).toString() : fixed;
};

export const formatIOPS = (value) => {
    if (value >= 1_000_000_000) {
        return trimDecimal(value / 1_000_000_000) + "B IOPS";
    } else if (value >= 1_000_000) {
        return trimDecimal(value / 1_000_000) + "M IOPS";
    } else if (value >= 1_000) {
        return trimDecimal(value / 1_000) + "k IOPS";
    } else {
        return value.toFixed(0) + " IOPS";
    }
};

export const formatThroughput = (valueInMBps) => {
    if (valueInMBps >= 1000) {
        return trimDecimal(valueInMBps / 1000) + " GB/s";
    } else if (valueInMBps >= 1) {
        return trimDecimal(valueInMBps) + " MB/s";
    } else {
        return trimDecimal(valueInMBps * 1000) + " kB/s";
    }
};

