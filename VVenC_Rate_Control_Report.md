# VVenC Rate Control: Algorithms and Mechanisms

## 1. Introduction

Rate control (RC) in video encoding is essential for ensuring that the encoded bitstream meets a target bitrate, which is crucial for applications like streaming, broadcasting, and storage with limited bandwidth or capacity. Effective rate control aims to distribute the available bits optimally among frames and regions within frames to maximize perceived video quality while adhering to bitrate constraints.

The VVenC encoder implements several rate control strategies to cater to different encoding scenarios:
*   **Fixed QP (Quantization Parameter) Mode**: Encodes the sequence with a constant QP, resulting in variable bitrate.
*   **Average Bitrate (ABR) Mode**: Aims to achieve a specified average bitrate over the sequence. This can be implemented as:
    *   Single-pass ABR.
    *   Single-pass ABR with a lookahead mechanism to analyze upcoming frames.
    *   Multi-pass ABR, where one or more initial passes gather statistics to improve rate allocation in the final pass.
*   **Perceptual QP Adaptation (QPA)**: Can be combined with ABR modes to modulate QP at a finer granularity based on local content characteristics, aiming to improve visual quality.

This report details the algorithms, key data structures, and configuration aspects of VVenC's rate control mechanisms.

## 2. Key Classes and Data Structures

The core rate control logic in VVenC is primarily managed by the `RateCtrl` class, supported by several key data structures:

*   **`RateCtrl` Class**:
    *   Located in `source/Lib/EncoderLib/RateCtrl.h` and `.cpp`.
    *   Orchestrates the overall rate control process, including initialization, pass management, picture-level QP and lambda determination, and interaction with lookahead or multi-pass statistics.

*   **`TRCPassStats` Structure**:
    *   Defined in `RateCtrl.h`.
    *   Stores frame-level statistics collected during a first pass (in multi-pass RC) or by the lookahead analysis.
    *   **Key Members**: `poc`, `qp` (used in the analysis pass), `lambda`, `visActY` (luma visual activity), `numBits` (actual bits consumed in the analysis pass), `psnrY`, `isIntra`, `tempLayer`, `isStartOfIntra`, `isStartOfGop`, `gopNum`, `scType` (scene cut type), `spVisAct` (spatial visual activity), `motionEstError`, `minNoiseLevels` (noise characteristics), `isNewScene` (flagged by scene cut detection), `refreshParameters` (flag to reset RC state), `frameInGopRatio` (frame's bit proportion within its GOP), `targetBits` (calculated target for the current pass).
    *   This structure is crucial for transferring information from analysis stages to the final encoding pass.

*   **`EncRCSeq` Class**:
    *   Defined in `RateCtrl.h`. Represents sequence-level rate control state and parameters.
    *   **Key Members**: `twoPass` (bool), `isLookAhead` (bool), `targetRate`, `maxGopRate`, `frameRate`, `gopSize`, `intraPeriod`, `bitsUsed` (total bits consumed so far), `estimatedBitUsage` (total target bits allocated so far), `qpCorrection[8]` (QP correction factor per temporal layer), `actualBitCnt[8]` and `targetBitCnt[8]` (accumulated actual/target bits per temporal layer), `lastAverageQP`, `lastIntraQP`, `lastIntraSM` (intra GOP stationarity measure), `firstPassData` (a list of `TRCPassStats` for the current processing window).
    *   It maintains the overall budget and adapts its parameters based on encoding history and lookahead/first-pass data.

*   **`EncRCPic` Class**:
    *   Defined in `RateCtrl.h`. Represents picture-level rate control state.
    *   **Key Members**: `encRCSeq` (pointer to parent sequence RC object), `frameLevel` (temporal layer + 1, or 0 for intra), `targetBits` (final target bits for this picture), `tmpTargetBits` (initial target bits before budget adjustments), `picQP` (actual average QP used), `picBits` (actual bits consumed), `poc`, `refreshParams` (if RC state should be reset for this pic), `visActSteady` (visual activity from `TRCPassStats`).
    *   It calculates the specific QP and lambda for a picture, and updates `EncRCSeq` after the picture is encoded.

**Interrelation**: `EncRCSeq` holds the global strategy and accumulated statistics. For each picture, an `EncRCPic` instance is created, using information from `EncRCSeq` (including relevant `TRCPassStats` if applicable) to determine its `targetBits` and initial QP. After encoding, `EncRCPic` updates `EncRCSeq` with the actual results, closing the feedback loop.

## 3. Core Rate Control Mechanism

### 3.1. Initialization and Configuration

*   **`RateCtrl::init(const VVEncCfg& encCfg)`**:
    *   This is the main initialization point, called when the encoder starts.
    *   It creates an `EncRCSeq` instance and calls `encRCSeq->create(...)`.
    *   `encRCSeq->create()` sets up sequence-level parameters based on `vvencCfg` values like `m_RCTargetBitrate`, `m_RCMaxBitrate`, `m_FrameRate`, `m_GOPSize`, `m_IntraPeriod`, `m_LookAhead`, `m_RCNumPasses`, and `m_internalBitDepth`.
    *   It calculates `maxGopRate` to cap GOP bit consumption, derived from `m_RCMaxBitrate` and `m_RCTargetBitrate`.

*   **`RateCtrl::setRCPass(const VVEncCfg& encCfg, int pass, const char* statsFName)`**:
    *   Configures `RateCtrl` for a specific encoding pass (relevant for multi-pass RC).
    *   Sets `rcPass` and `rcIsFinalPass`.
    *   **If `rcIsFinalPass` is true and `statsFName` is provided**: It attempts to load statistics from the file specified by `statsFName`.
        *   `openStatsFile()` opens the file for reading.
        *   `readStatsHeader()` and `readStatsFile()` parse the JSON-formatted statistics, populating `m_listRCFirstPassStats` with `TRCPassStats` objects.
        *   If `encCfg.m_FirstPassMode > 2` (first pass used downsampling), `adjustStatsDownsample()` scales the loaded bit counts.
    *   **If `rcIsFinalPass` is false and `statsFName` is provided**: It opens the file for writing, and `writeStatsHeader()` creates the header. Statistics will be written by `storeStatsData`.
    *   The loaded/prepared `m_listRCFirstPassStats` are then made available to `EncRCSeq` when `RateCtrl::init()` is subsequently called by `EncLib::initPass()`.

### 3.2. Frame/GOP Level Bit Allocation and Initial QP (`initRateControlPic`)

The function `RateCtrl::initRateControlPic(Picture& pic, Slice* slice, int& qp, double& finalLambda)` is invoked before encoding each picture to determine its target bits and initial QP.

*   **Target Bit Allocation**:
    1.  **Baseline Target**: If first-pass/lookahead statistics (`TRCPassStats`) are available for the current picture (`it->poc == slice->poc`), its `it->targetBits` (pre-scaled in `processGops`) serves as the initial estimate (`encRcPic->tmpTargetBits`).
    2.  **Budget Compensation**: The core of the target bit allocation is adjusting this baseline based on the deviation of actual bits consumed (`encRCSeq->bitsUsed`) from the estimated target so far (`encRCSeq->estimatedBitUsage`):
        `d = encRcPic->tmpTargetBits + std::min((int64_t)encRCSeq->maxGopRate, encRCSeq->estimatedBitUsage - encRCSeq->bitsUsed) * tmpVal * it->frameInGopRatio;`
        *   `tmpVal` (typically 0.5) controls how aggressively the deviation is compensated. It's adjusted for Intra GOPs using `encRCSeq->lastIntraSM` (a measure of I-GOP stationarity).
        *   `it->frameInGopRatio` (calculated in `processGops`) distributes the compensation proportionally within the GOP.
    3.  **Constraints**: The calculated target `d` is clipped by `dLimit` (to prevent excessive short-term fluctuations) and potentially by `encRCSeq->maxGopRate` (especially for GOP start frames).
    4.  The final `encRcPic->targetBits` is set.

*   **Initial QP Determination**:
    1.  **Reference QP**: The QP from the first pass/lookahead (`firstPassSliceQP = it->qp`) is used as a reference.
    2.  **R-QP Model**: A rate-quantization model adjusts `firstPassSliceQP` based on the ratio of the current `encRcPic->targetBits` to the bits consumed in the first pass (`it->numBits`). The formula is `newQP = prevQP - C * sqrt(prevQP) * log(targetBits_curr / actualBits_prev)`.
    3.  **Complexity/Activity Adjustment**:
        *   `tmpVal = updateQPstartModelVal() + log(sqrOfResRatio) / log(2.0);`
            *   `updateQPstartModelVal()`: Calculates a QP based on average noise levels (`m_minNoiseLevels`) from lookahead/first pass. Higher noise suggests a higher base QP.
            *   `log(sqrOfResRatio)`: Resolution-dependent QP adjustment.
        *   The derived `sliceQP` is pushed towards `tmpVal` if `tmpVal` is higher than the rate-derived QP, effectively making simpler content use higher QPs.
    4.  **Temporal Layer Correction**: `encRCSeq->qpCorrection[frameLevel]` (updated after each picture based on per-layer bit deviations) provides feedback to adjust QP for each temporal layer.
    5.  **QP Clipping (`EncRCPic::clipTargetQP`)**: The resulting `sliceQP` is clipped based on:
        *   The overall sequence base QP.
        *   QPs of previous pictures in the same and lower temporal layers to ensure stability.
        *   `MAX_QP`.
        *   If QP is changed by clipping, `targetBits` are also adjusted.
    6.  **Lambda Derivation**: `finalLambda` is derived from the final `sliceQP` and the first-pass lambda using `lambda = it->lambda * pow(2.0, double(sliceQP - firstPassSliceQP) / 3.0)`.

*   **`refreshParameters` Flag**: If true (due to scene cut or start of sequence), QP clipping ranges are widened, and some RC state like `encRCSeq->lastAverageQP` might be reset, allowing more QP flexibility.

### 3.3. CTU/Block Level QP Adaptation

Once the frame-level QP is set by `RateCtrl`, `EncCu` can further modulate it at the CTU or block level, primarily when `m_usePerceptQPA` is enabled in `vvencCfg`.

*   **Mechanism**:
    *   `EncCu::xCompressCtu` checks if QP adaptation is enabled for the current quantization group.
    *   If `m_usePerceptQPA` is true:
        *   The base QP for the CTU can be taken from `pic->ctuAdaptedQP[ctuRsAddr]`, which is likely pre-calculated using lookahead statistics (e.g., by `BitAllocation::updateCtuData`).
        *   For sub-CTU blocks (if `m_cuQpDeltaSubdiv > 0`), `BitAllocation::applyQPAdaptationSubCtu` is called. This function typically calculates local block activity (e.g., variance from original pixels) and uses it along with `minNoiseLevels` (provided by `RateCtrl` from lookahead/first-pass data) to derive a QP delta or a new QP for that specific block.
    *   If `m_blockImportanceMapping` is enabled (and QPA is off), a pre-defined QP offset from `pic->m_picShared->m_ctuBimQpOffset` is applied to the CTU's base QP.
*   **Interaction with `RateCtrl`**:
    *   `RateCtrl` provides the anchor frame-level QP and the `minNoiseLevels` statistics from the lookahead/first pass.
    *   `EncCu` and `BitAllocation` use these inputs, plus local block activity, to perform finer-grained QP adjustments. There's no direct per-block feedback loop to `RateCtrl`'s buffer models from this stage.

## 4. Advanced RC Strategies

### 4.1. Lookahead Mechanism (`m_LookAhead = 1`)

When lookahead is enabled (and `m_RCNumPasses` is typically 1):
*   **`EncLib::xInitRCCfg` and `EncLib::initPass`**:
    *   `m_firstPassCfg` is initialized with a fast preset.
    *   An `EncGOP` instance, `m_preEncoder`, is created using `m_firstPassCfg`. This `m_preEncoder` runs ahead of the main `m_gopEncoder`.
*   **Data Collection by `m_preEncoder`**:
    *   `m_preEncoder` performs a lightweight encoding of future frames.
    *   It calls `RateCtrl::addRCPassStats` to populate `TRCPassStats` for these future frames. These stats include `visActY`, `numBits` (from the lightweight encode), `qp`, `lambda`, `motionEstError`, `minNoiseLevels`, etc.
    *   `RateCtrl::storeStatsData` then places these `TRCPassStats` into `m_firstPassCache`.
*   **Using Lookahead Data in `RateCtrl`**:
    *   When `RateCtrl::initRateControlPic` is called for the main encoder, `RateCtrl::processFirstPassData` is invoked.
    *   This function moves a relevant segment of `TRCPassStats` from `m_firstPassCache` (representing the current lookahead window) into `encRCSeq->firstPassData`.
    *   **Scene Cut Detection (`detectSceneCuts`)**: Operates on `encRCSeq->firstPassData` to identify scene changes in the near future. Flags `isNewScene` and `refreshParameters` in `TRCPassStats`, allowing `initRateControlPic` to adapt QP more aggressively.
    *   **Adaptive QP and Bit Allocation**: The `visActY`, `numBits`, `lambda`, `qp`, `minNoiseLevels` from the lookahead stats are used in `initRateControlPic` exactly as described in Section 3.2, allowing QP and target bits to be set based on the complexity of upcoming frames.
    *   **Rate Boosting (`getLookAheadBoostFac`)**: Uses `m_gopMEErrorCBuf` (populated with `motionEstError` from lookahead stats via `updateMotionErrStatsGop`) to calculate `encRCSeq->rateBoostFac`. This factor can temporarily increase target bits for GOPs identified as complex or high-motion by the lookahead, allowing the encoder to spend more bits proactively.
    *   **QP Start Model (`updateQPstartModelVal`)**: Uses `m_minNoiseLevels` (from lookahead) to adjust the baseline QP in the R-QP model, adapting to content texture/noise.

### 4.2. Multi-Pass Rate Control (`m_RCNumPasses > 1`)

*   **First Pass**:
    *   `EncLib::initPass` configures `RateCtrl` for pass 0 and uses `m_firstPassCfg` (fast preset, often fixed QP).
    *   `RateCtrl::storeStatsData` writes `TRCPassStats` for every frame to a statistics file (`m_RCStatsFileName`) in JSON format.
*   **Final Pass**:
    *   `EncLib::initPass` configures `RateCtrl` for the final pass.
    *   `RateCtrl::setRCPass` loads all `TRCPassStats` from `m_RCStatsFileName` into `m_listRCFirstPassStats`.
    *   `RateCtrl::processFirstPassData` then processes this complete set of statistics:
        *   `detectSceneCuts` operates on the entire sequence's stats.
        *   `processGops` performs global bit distribution:
            *   Calculates `bp1pf` (average bits per frame from the first pass for the *entire sequence*).
            *   Computes a global `ratio` to scale first-pass bits to the final pass's target bitrate.
            *   Assigns initial `targetBits` and `frameInGopRatio` to all frames based on this global scaling.
            *   Performs pre-capping of GOPs if `maxGopRate` is active, redistributing bits globally.
    *   `initRateControlPic` then uses these globally adjusted `targetBits` and other stats for per-frame QP/lambda calculation, similar to the lookahead case but with statistics derived from a full previous pass.
    *   `RateCtrl::getBaseQP()` uses the full first-pass stats to derive a more stable initial QP for the second pass.

## 5. HRD Compliance

VVenC's rate control aims to produce a bitstream that can be HRD compliant, although it doesn't directly model an HRD buffer.

*   **`EncHRD` Role**:
    *   The `EncHRD` class is responsible for initializing and signaling HRD parameters in the SPS VUI (e.g., `bit_rate_value_minus1`, `cpb_size_value_minus1`).
    *   The CPB size is typically derived from the Profile-Tier-Level (PTL) of the sequence.
    *   The bitrate signaled is usually the `m_RCTargetBitrate`.
    *   `EncHRD` also helps generate Buffering Period and Picture Timing SEI messages.
*   **`RateCtrl` Contribution**:
    *   `RateCtrl` helps by trying to meet the `m_RCTargetBitrate`.
    *   The `encRCSeq->maxGopRate` acts as a soft constraint preventing excessive bit peaks over a GOP, which helps avoid CPB overflow.
    *   The internal RC buffer model (`estimatedBitUsage` vs. `bitsUsed`) aims to keep the output rate smooth around the target.
    *   QP clipping in `EncRCPic::clipTargetQP` also helps stabilize picture sizes.
*   **No Direct Feedback**: `EncHRD` does not provide direct feedback (e.g., buffer fullness) to `RateCtrl` for dynamic QP adjustment based on a strict HRD model during encoding. Compliance is achieved if `RateCtrl`'s output naturally fits within the signaled HRD parameters.

## 6. Command-Line Usage for RC Modes (`vvencapp`)

The `vvencapp` application uses command-line arguments to set parameters in the `vvenc_config` structure.

*   **Fixed QP Mode**:
    *   **Command**: `--qp <Q>` (e.g., `--qp 32`). Ensure target bitrate is off.
    *   **`vvenc_config` params**: `m_QP = Q`, `m_RCTargetBitrate = 0`.

*   **ABR Single-Pass Mode (No Lookahead/Multi-Pass)**:
    *   **Command**: `--bitrate <B>` (e.g., `--bitrate 1000000`).
    *   **`vvenc_config` params**: `m_RCTargetBitrate = B`, `m_RCNumPasses` typically defaults to 1 or is explicitly set to 1, `m_LookAhead = 0`.

*   **ABR Two-Pass Mode**:
    *   **Pass 1 Command**: `--bitrate <B> --passes 2 --pass 0 --rcstatsfile <stats.json>`
    *   **Pass 2 Command**: `--bitrate <B> --passes 2 --pass 1 --rcstatsfile <stats.json>`
    *   **`vvenc_config` params**: `m_RCTargetBitrate = B`, `m_RCNumPasses = 2`, `m_RCPass = {0 or 1}`. `m_RCStatsFileName` (internal, set via app logic based on `--rcstatsfile`).

*   **ABR Single-Pass with Lookahead**:
    *   **Command**: `--bitrate <B> --lookahead 1` (or a different lookahead depth if supported by app).
    *   **`vvenc_config` params**: `m_RCTargetBitrate = B`, `m_LookAhead = 1` (or other depth), `m_RCNumPasses` typically defaults to 1.

*   **Enabling Perceptual QP Adaptation (QPA)**:
    *   **Command**: `--qpa 1` (or other QPA mode if available, e.g., `--qpa 2`). This is typically combined with an ABR mode (lookahead or two-pass, as QPA benefits from statistics).
    *   **`vvenc_config` param**: `m_usePerceptQPA = true`.

## 7. Conclusion

VVenC offers a flexible and robust rate control system. It supports basic fixed QP encoding, single-pass ABR, and more advanced strategies like two-pass encoding and single-pass with lookahead. These advanced modes leverage statistics from previous or future frames to make informed decisions about bit allocation and QP selection, aiming for optimal quality at the target bitrate. Furthermore, perceptual QP adaptation allows for finer-grained QP adjustments based on content characteristics, enhancing visual quality. While not directly modeling an HRD buffer, its mechanisms for bitrate smoothing and peak limitation contribute significantly to producing HRD-compliant streams.
