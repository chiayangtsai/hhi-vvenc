# VVenC Rate Control: Algorithms and Mechanisms

## 1. Introduction

Rate control (RC) is a critical component in modern video encoding systems. Its fundamental purpose is to manage the output bitrate of the encoder to meet specific constraints, such as those imposed by transmission channels or storage media. Effective rate control strives to achieve a target bitrate while optimizing video quality consistently across different parts of the video sequence and ensuring that the generated bitstream can be decoded smoothly by a Hypothetical Reference Decoder (HRD). This often involves dynamically adjusting encoding parameters, most notably Quantization Parameters (QPs), in response to video content complexity and buffer fullness.

The VVenC encoder, an implementation of the H.266/VVC (Versatile Video Coding) standard, incorporates a sophisticated and flexible rate control system designed to address these needs. It provides users with several strategies to manage the trade-off between bitrate, quality, and encoding complexity. This report will delve into the details of VVenC's rate control algorithms and mechanisms, covering its main approaches:
*   **Fixed QP Mode**: Encoding with a constant Quantization Parameter, leading to variable bitrate but predictable quality for a given QP.
*   **Average Bitrate (ABR) Mode**: Targeting a specific average bitrate over the duration of the sequence. VVenC supports several ABR variations:
    *   **Single-Pass ABR**: Makes decisions based on past encoding statistics within the current pass.
    *   **Single-Pass ABR with Lookahead**: Enhances single-pass ABR by analyzing a window of upcoming frames to make more informed bit allocation and QP decisions.
    *   **Multi-Pass ABR**: Utilizes one or more initial encoding passes to gather detailed statistics about the video content, which are then used in a final pass to achieve more accurate rate allocation and potentially higher quality.
*   **Perceptual QP Adaptation (QPA)**: A technique, often used in conjunction with ABR modes, that modulates QP at a finer granularity (e.g., per Coding Tree Unit or block) based on local content characteristics, aiming to improve visual quality by allocating more bits to perceptually important or complex regions.

This document will explore the implementation details of these strategies, the key data structures involved, configuration options, and how they interact to control the encoding process.


## 2. Key Classes and Data Structures

The VVenC encoder's rate control mechanism is managed through a set of interconnected classes and data structures that store configuration, state, and statistical information at different levels (sequence, picture, and for pass-specific data).

*   **`RateCtrl` Class**:
    *   The main class responsible for orchestrating rate control. It is defined in `source/Lib/EncoderLib/RateCtrl.h` and implemented in `source/Lib/EncoderLib/RateCtrl.cpp`.
    *   It initializes and manages sequence-level (`EncRCSeq`) and picture-level (`EncRCPic`) rate control objects.
    *   It handles the logic for different RC modes (single-pass, multi-pass, lookahead) by processing statistics and determining QP values for encoding.

*   **`TRCPassStats` Structure**:
    *   **Purpose**: This structure, defined in `RateCtrl.h`, serves as a container for detailed frame-level statistics. These statistics are primarily collected during a first encoding pass (in a multi-pass scenario) or by the lookahead analysis stage. This information is then used in the final encoding pass to make more informed rate control decisions.
    *   **Key Members**:
        *   `poc` (int): Picture Order Count, identifying the frame.
        *   `qp` (int): The Quantization Parameter used for this frame during the analysis/first pass.
        *   `lambda` (double): The Lagrange multiplier associated with the QP used in the analysis/first pass.
        *   `visActY` (uint16_t): A measure of luma visual activity or complexity of the frame content.
        *   `numBits` (uint32_t): The actual number of bits consumed to encode the frame in the analysis/first pass.
        *   `psnrY` (double): The PSNR (Peak Signal-to-Noise Ratio) for the luma component achieved in the analysis/first pass.
        *   `isIntra` (bool): Flag indicating if the frame was encoded as an Intra frame.
        *   `tempLayer` (int): The temporal layer of the frame.
        *   `isStartOfIntra` (bool): Flag indicating if this frame is the start of an intra period.
        *   `isStartOfGop` (bool): Flag indicating if this frame is the start of a GOP.
        *   `gopNum` (int): The GOP number this frame belongs to.
        *   `scType` (SceneType): Indicates if the frame is part of a scene cut, and the type of scene cut.
        *   `spVisAct` (int): Spatial visual activity, a more localized measure of complexity.
        *   `motionEstError` (uint16_t): An indicator of motion complexity or prediction difficulty.
        *   `minNoiseLevels[QPA_MAX_NOISE_LEVELS]` (uint8_t[]): Array storing statistics about noise levels in different signal frequency bands, used for perceptual QPA.
        *   `isNewScene` (bool): Flag set by `RateCtrl::detectSceneCuts` if this frame is identified as the start of a new scene.
        *   `refreshParameters` (bool): Flag indicating if RC parameters should be refreshed/reset for this frame (e.g., at a scene cut).
        *   `frameInGopRatio` (double): The proportion of this frame's target bits relative to its GOP's total target bits (calculated in the final pass).
        *   `targetBits` (int): The calculated target number of bits for this frame in the current (final) encoding pass.
        *   `addedToList` (bool): Internal flag used during lookahead processing.

*   **`EncRCSeq` Class**:
    *   **Role**: Defined in `RateCtrl.h`, this class manages the sequence-level state and parameters for rate control. It holds the overall configuration for the RC process throughout the encoding of a sequence.
    *   **Key Members**:
        *   `twoPass` (bool): True if two-pass rate control is active.
        *   `isLookAhead` (bool): True if lookahead rate control is active.
        *   `isIntraGOP` (bool): Flag indicating if the current GOP is being treated as an all-intra GOP for bit allocation purposes (can be influenced by scene cuts or lookahead).
        *   `isRateSavingMode` (bool): Flag to indicate if the RC should try to save bits (e.g., towards the end of the sequence or if approaching max rate).
        *   `frameRate` (double): Frame rate of the sequence.
        *   `targetRate` (int): Overall target bitrate for the sequence.
        *   `maxGopRate` (int): Calculated maximum bits allowed for a single GOP, derived from `m_RCMaxBitrate` and `m_RCTargetBitrate`.
        *   `gopSize` (int): Nominal GOP size.
        *   `intraPeriod` (unsigned): Period between I-frames.
        *   `bitDepth` (int): Bit depth of the luma component.
        *   `bitsUsed` (int64_t): Total actual bits consumed by the encoder so far.
        *   `estimatedBitUsage` (int64_t): Total target bits allocated to pictures encoded so far. The difference between `bitsUsed` and `estimatedBitUsage` reflects the current buffer status.
        *   `rateBoostFac` (double): A factor used in lookahead RC to temporarily boost bit allocation for complex GOPs.
        *   `qpCorrection[8]` (double[]): QP correction values for each temporal layer, used as a feedback mechanism.
        *   `actualBitCnt[8]`, `targetBitCnt[8]` (uint64_t[]): Accumulated actual and target bits per temporal layer.
        *   `lastAverageQP` (int): Average QP of recently encoded frames.
        *   `lastIntraQP` (int): QP of the last intra frame.
        *   `lastIntraSM` (double): Temporal stationarity measure of the last intra GOP.
        *   `firstPassData` (std::list<TRCPassStats>): A list holding `TRCPassStats` objects for the current processing window (either loaded from a file for two-pass or populated from a cache for lookahead).
        *   `minEstLambda`, `maxEstLambda` (double): Minimum and maximum estimated lambda values.

*   **`EncRCPic` Class**:
    *   **Role**: Defined in `RateCtrl.h`, this class manages picture-level rate control state and parameters for a single picture being encoded.
    *   **Key Members**:
        *   `encRCSeq` (EncRCSeq*): A pointer to the parent `EncRCSeq` object, providing access to sequence-level information.
        *   `frameLevel` (int): The temporal layer of the picture (adjusted: non-I is TLayer+1, I is 0).
        *   `targetBits` (int): The final target number of bits allocated to this picture after all adjustments.
        *   `tmpTargetBits` (int): An initial target number of bits for this picture before budget-based adjustments.
        *   `poc` (int): Picture Order Count of the current picture.
        *   `refreshParams` (bool): Indicates if RC parameters should be reset for this picture (e.g., if it's a scene cut).
        *   `visActSteady` (uint16_t): The visual activity (e.g., `visActY` from `TRCPassStats`) of this picture, used for QP adaptation.
        *   `picQP` (int16_t): The actual average QP used for encoding this picture (stored after encoding).
        *   `picBits` (uint16_t): The actual number of bits consumed by this picture (stored after encoding).

*   **Interrelation of Structures**:
    1.  The `RateCtrl` object owns and initializes an `EncRCSeq` object for the entire sequence.
    2.  When preparing to encode a picture, `RateCtrl` creates an `EncRCPic` object. This `EncRCPic` object holds a pointer to the `EncRCSeq` instance, allowing it to access sequence-level parameters and statistics.
    3.  The `EncRCSeq` object's `firstPassData` list (which contains `TRCPassStats` objects from either a lookahead cache or a first-pass file) provides crucial input (like initial bit estimates, visual activity, QP from the first pass) to the `EncRCPic` object (via `RateCtrl::initRateControlPic`) for determining the current picture's `targetBits` and initial QP.
    4.  After the picture is encoded, the `EncRCPic` object's `updateAfterPicture` method is called with the actual bits consumed and the average QP used. This method updates its own `picBits` and `picQP`.
    5.  Crucially, `EncRCPic::updateAfterPicture` also calls `encRCSeq->updateAfterPic()`. This updates the `EncRCSeq` object's state, such as `bitsUsed`, `estimatedBitUsage`, and the per-temporal-layer statistics (`actualBitCnt`, `targetBitCnt`, `qpCorrection`).
    6.  This feedback loop ensures that the `EncRCSeq` object maintains an up-to-date model of the encoding process, which is then used to guide subsequent `EncRCPic` initializations, thereby adapting to the evolving characteristics of the video sequence and the encoder's performance. `EncRCPic` instances are typically stored in a list (`m_listRCPictures` in `RateCtrl`) to provide a history for QP clipping and other temporal RC decisions.

These structures work together to implement the rate control logic, from high-level sequence parameters down to per-picture decisions, using past information and (if available) future information (via lookahead or multi-pass) to manage the bitrate effectively.


## 3. Core Rate Control Mechanism

The core rate control mechanism in VVenC operates at multiple levels: initialization based on global configurations, frame/GOP level bit allocation and QP setting, and finer-grained CTU/block level QP adaptation for perceptual quality.

### 3.1. Initialization and Configuration

The rate control process begins with the initialization of the `RateCtrl` class, which sets up the overall strategy based on user-provided configurations from `vvencCfg`.

*   **`RateCtrl::init(const VVEncCfg& encCfg)`**: This is the primary initialization for the sequence.
    *   It instantiates `EncRCSeq` (sequence-level RC state) and calls `EncRCSeq::create(...)`.
    *   `EncRCSeq::create` is populated with key parameters from `encCfg`:
        *   `m_RCTargetBitrate`, `m_RCMaxBitrate` (used to derive `maxGopRate`).
        *   Frame rate (`m_FrameRate`, `m_FrameScale`), GOP size (`m_GOPSize`), intra period (`m_IntraPeriod`).
        *   Flags for `m_LookAhead` and `m_RCNumPasses`.
        *   Internal bit depth (`m_internalBitDepth`).
    *   The initial QP (`m_QP`) from `vvencCfg` serves as a baseline if RC is off, or as a starting point for some RC calculations (e.g., `RCInitialQP` can influence `getBaseQP`).
    *   HRD-related hints like `m_RCMaxBitrate` are used to derive `maxGopRate` in `EncRCSeq`, providing a loose cap on GOP bitrates. Direct HRD buffer modeling for QP decisions is not a primary function of `RateCtrl::init`.

*   **`RateCtrl::setRCPass(const VVEncCfg& encCfg, int pass, const char* statsFName)`**:
    *   This function configures `RateCtrl` for a specific pass in multi-pass encoding.
    *   It sets `rcPass` and `rcIsFinalPass`.
    *   If it's the final pass and `statsFName` is provided, it loads first-pass statistics (JSON format) into `m_listRCFirstPassStats`. These stats are then passed to `EncRCSeq` when `RateCtrl::init` is called by `EncLib` for that pass.
    *   If it's a first pass, it prepares to write statistics to `statsFName`.
    *   The availability of these statistics significantly influences the behavior of `EncRCSeq` and `EncRCPic` for bit allocation and QP determination in the final pass.

### 3.2. Frame/GOP Level Bit Allocation and QP Determination

For each picture, `RateCtrl::initRateControlPic(Picture& pic, Slice* slice, int& qp, double& finalLambda)` is called to determine its target bits and initial QP. An `EncRCPic` object is created to manage this picture's RC state, linked to the main `EncRCSeq` object.

*   **Target Bit Allocation (`EncRCPic::targetBits`)**:
    1.  **Baseline from Stats**: If first-pass or lookahead statistics (`TRCPassStats`) are available for the current Picture Order Count (POC), the `targetBits` field from these stats (which itself was scaled from actual first-pass bits in `RateCtrl::processGops`) serves as an initial estimate (`encRcPic->tmpTargetBits`).
    2.  **Budget Compensation**: This baseline is adjusted based on the overall sequence-level bit budget status:
        `d = encRcPic->tmpTargetBits + std::min((int64_t)encRCSeq->maxGopRate, encRCSeq->estimatedBitUsage - encRCSeq->bitsUsed) * tmpVal * it->frameInGopRatio;`
        *   `encRCSeq->estimatedBitUsage - encRCSeq->bitsUsed` reflects the current surplus or deficit.
        *   `tmpVal` (typically ~0.5, adjusted for Intra GOPs based on `encRCSeq->lastIntraSM`) controls the aggressiveness of compensation.
        *   `it->frameInGopRatio` (frame's bit share within its GOP, from `processGops`) apportions the compensation.
    3.  **Clipping/Constraints**: The resulting target `d` is clipped by `dLimit` (to prevent drastic deviations from the initial estimate) and potentially by `encRCSeq->maxGopRate` to manage GOP-level peaks. The final value is stored in `encRcPic->targetBits`.

*   **Initial Picture QP Determination (`sliceQP` and `finalLambda`)**:
    1.  **Reference QP**: The QP from the first-pass/lookahead stats (`firstPassSliceQP = it->qp`) is the starting point.
    2.  **R-QP Model**: An R-QP (Rate-Quantization) model adjusts `firstPassSliceQP` based on the ratio of the current `encRcPic->targetBits` to the bits from the first pass (`it->numBits`). The formula `sliceQP = firstPassSliceQP - C * sqrt(firstPassSliceQP) * log(targetBits_curr / actualBits_prev)` is applied.
    3.  **Complexity/Activity Adjustment**:
        *   A scene complexity/texture-based QP (`tmpVal`) is calculated using `RateCtrl::updateQPstartModelVal()` (which considers `m_minNoiseLevels` from stats) and a resolution-dependent term.
        *   The `sliceQP` is nudged towards this `tmpVal`, typically increasing QP for simpler content: `sliceQP += factor * std::max(0.0, tmpVal - rate_derived_QP)`.
    4.  **Temporal Layer Correction**: `encRCSeq->qpCorrection[frameLevel]` provides a feedback term based on historical bit deviations for each temporal layer, further refining `sliceQP`.
    5.  **QP Clipping (`EncRCPic::clipTargetQP`)**: The calculated `sliceQP` is clipped to ensure stability, considering QPs of previous frames in the same and lower temporal layers, and the overall sequence base QP. If `sliceQP` is significantly altered, `targetBits` are also re-scaled.
    6.  **Lambda Derivation**: `finalLambda` is computed from the final `sliceQP` and the first-pass lambda (`it->lambda`) using the relationship `lambda_new = lambda_prev * 2^((QP_new - QP_prev)/3.0)`.

*   **Role of `EncRCSeq` and `EncRCPic`**:
    *   `EncRCSeq` maintains the global budget, stores/processes first-pass/lookahead stats (`TRCPassStats` in `firstPassData`), and holds long-term correction factors (`qpCorrection`).
    *   `EncRCPic` uses this sequence-level context to derive its specific `targetBits` and initial `qp`. After encoding, `EncRCPic::updateAfterPicture` reports actual bits and QP back to `EncRCSeq`, which updates its models for subsequent frames.

### 3.3. CTU/Block Level QP Adaptation (Perceptual QPA)

When enabled, Perceptual QP Adaptation allows `EncCu` to modulate the frame-level QP at a finer granularity (CTU or sub-CTU level).

*   **Enabling**: Primarily controlled by `m_usePerceptQPA` in `vvencCfg`. This typically sets `pps.useDQP` to true. `m_cuQpDeltaSubdiv` controls the depth to which QP can be varied within a CTU.
*   **Activity Measures and Usage**:
    *   Lookahead/first-pass analysis (managed by `RateCtrl`) gathers activity metrics like `visActY` (frame-level visual activity) and `minNoiseLevels` (noise characteristics), stored in `TRCPassStats`.
    *   **CTU-Level QP (`pic->ctuAdaptedQP`)**:
        *   Before `EncCu` processes a CTU, `pic->ctuAdaptedQP[ctuRsAddr]` (and `pic->ctuQpaLambda`) are often pre-calculated (e.g., by `BitAllocation::updateCtuData` or a similar function that has access to frame-wide lookahead results). This pre-calculated QP becomes the base QP for the current CTU within `EncCu::xCompressCtu`.
    *   **Sub-CTU QP (`BitAllocation::applyQPAdaptationSubCtu`)**:
        *   If `m_cuQpDeltaSubdiv > 0` and QPA is active, `EncCu::xCompressCtu` calls `BitAllocation::applyQPAdaptationSubCtu` for smaller blocks (quantization groups or CUs).
        *   This function likely calculates a *local* activity measure for the current block being processed (e.g., variance of original luma samples).
        *   It then uses this local activity, potentially combined with the frame-level `visActY` (passed as `encRcPic->visActSteady`) and the `minNoiseLevels` (obtained via `m_pcRateCtrl->getMinNoiseLevels()`), to compute a QP delta or a new QP for that specific block. Higher local activity generally results in a lower QP.
*   **Influence of Noise Levels**: The `minNoiseLevels` obtained from lookahead are passed to `BitAllocation::applyQPAdaptationSubCtu`. This allows the QP adaptation to be less aggressive in noisy regions (i.e., not lowering QP as much for high activity if it's likely noise) or to adapt differently based on texture characteristics identified by the noise analysis.
*   **Signaling Delta QP**: If the finally chosen QP for a block (after QPA) differs from the QP predicted from its neighbors, `EncCu::xCheckDQP` ensures the delta QP is signaled in the bitstream.

This layered approach allows VVenC to make global bit allocation decisions at the frame/GOP level based on overall targets and sequence characteristics, and then refine these decisions locally at the CTU/block level to enhance perceptual quality when QPA is enabled.


## 4. Advanced Rate Control Strategies

Beyond basic single-pass ABR, VVenC implements more advanced rate control strategies, namely a lookahead mechanism and multi-pass encoding, to improve bit allocation and overall quality. These strategies rely on gathering information about future or past frame characteristics to make more informed encoding decisions.

### 4.1. Lookahead Mechanism

The lookahead mechanism in VVenC enables the rate controller to "see" a window of upcoming frames and adjust its parameters proactively.

*   **Enabling Lookahead**:
    *   Lookahead is primarily enabled by setting `m_LookAhead = 1` (or a higher value indicating lookahead depth, though typically 1 is used for a standard lookahead window) in the `vvencCfg` configuration.
    *   When `m_LookAhead` is active, `EncLib::xInitRCCfg` prepares a specific configuration (`m_firstPassCfg`) for the lookahead pass, usually a fast preset.
    *   `EncLib::initPass` then instantiates an `EncGOP` object, `m_preEncoder`, which uses this `m_firstPassCfg` to perform the lightweight analysis of future frames.

*   **Data Collection during Lookahead Pass**:
    *   The `m_preEncoder` stage in `EncLib` runs ahead of the main encoder (`m_gopEncoder`). It performs a simplified, faster encoding or analysis of the frames in the lookahead window.
    *   For each analyzed frame, `m_preEncoder` calls `RateCtrl::addRCPassStats`. This function populates a `TRCPassStats` structure with key metrics:
        *   Visual activity (`visActY`, `spVisAct`).
        *   Motion estimation error (`motionEstError`).
        *   Noise level characteristics (`minNoiseLevels`).
        *   Bits consumed, QP used, and lambda from this lightweight pass.
    *   `RateCtrl::storeStatsData` then takes these `TRCPassStats` and stores them in `RateCtrl::m_firstPassCache`. This cache acts as a sliding window of statistics for upcoming frames.

*   **Using Lookahead Data in `RateCtrl`**:
    Before the main encoder (`m_gopEncoder`) processes a picture or a group of pictures (a "chunk"), `RateCtrl::processFirstPassData` is called. This function:
    1.  Transfers a relevant segment of `TRCPassStats` from `m_firstPassCache` (representing the current lookahead window for the chunk being encoded) into `encRCSeq->firstPassData` (a list within the sequence-level RC object).
    2.  The statistics in `encRCSeq->firstPassData` are then used for several purposes:
        *   **Scene Cut Detection (`detectSceneCuts`)**: This function analyzes the `visActY` and `psnrY` values (from the lookahead pass) in `encRCSeq->firstPassData` to identify abrupt changes indicative of scene cuts. Frames identified as starting a new scene have their `TRCPassStats::isNewScene` and `TRCPassStats::refreshParameters` flags set. This allows `RateCtrl::initRateControlPic` to reset RC state (e.g., `qpCorrection`) and permit larger QP variations for the new scene.
        *   **GOP Processing and Bit Allocation (`processGops`)**: This function scales the `numBits` from the lookahead pass (stored in `TRCPassStats`) to derive initial `targetBits` and `frameInGopRatio` for each frame in the current processing window. This scaling is based on the overall target bitrate and the average bits consumed during the lookahead analysis for that window.
        *   **Adaptive QP / Perceptual QPA (`initRateControlPic` and CTU-level QPA)**:
            *   The `visActY` from `TRCPassStats` is used by `initRateControlPic` to set `EncRCPic::visActSteady`.
            *   The `minNoiseLevels` (noise characteristics) from `TRCPassStats` are used by `RateCtrl::updateQPstartModelVal()` to adjust a complexity-based QP component in the R-QP model within `initRateControlPic`.
            *   These noise levels are also passed to `BitAllocation::applyQPAdaptationSubCtu` (called during `EncCu` processing) to fine-tune QP at the CTU/block level for perceptual optimization.
        *   **Rate Boosting/Saving (`getLookAheadBoostFac`)**: `RateCtrl::updateMotionErrStatsGop` populates `m_gopMEErrorCBuf` with `motionEstError` values from the lookahead stats. `RateCtrl::getLookAheadBoostFac` analyzes this buffer to detect GOPs with significantly higher motion/complexity than their recent history. If such a GOP is detected, it returns a `rateBoostFac > 1.0`. `EncRCSeq::initRateControlPic` then uses this factor to temporarily increase the `targetBits` for frames in that complex GOP, allowing more bits to be spent proactively. Conversely, `encRCSeq->isRateSavingMode` can be set (e.g., towards the end of the sequence) to conserve bits.
        *   **Initial QP Modeling (`updateQPstartModelVal`)**: As mentioned, this function uses `m_minNoiseLevels` from the lookahead data to derive a QP that reflects the content's noise/texture. This influences the `tmpVal` in `initRateControlPic`'s QP calculation, helping to set a more content-appropriate starting QP.

*   **Proactive Nature**: The lookahead mechanism allows the rate controller to make proactive decisions. By analyzing upcoming frames, it can anticipate changes in complexity (scene cuts, high motion) and adjust bit allocation and QP settings *before* these frames are actually encoded by the main encoder, leading to more stable quality and better bitrate adherence.

### 4.2. Multi-Pass Rate Control

Multi-pass rate control, typically implemented as two passes, provides a more global view of the sequence's characteristics to optimize bit allocation.

*   **Enabling Multi-Pass**:
    *   This strategy is enabled by setting `m_RCNumPasses` in `vvencCfg` to a value greater than 1 (usually 2).
    *   `RateCtrl::setRCPass` uses the `pass` argument and `m_RCNumPasses` to set `rcIsFinalPass`, which dictates the RC's operational mode.

*   **First Pass**:
    *   **Goal**: The primary objective of the first pass is to perform a full encoding of the sequence (or a large segment) to gather comprehensive statistics about every frame.
    *   **Encoder Configuration**: `EncLib::initPass` configures the encoder using `m_firstPassCfg` (derived from `vvencPresetMode::VVENC_FIRSTPASS`). This preset usually employs faster encoding tools and often a simpler rate control scheme (e.g., fixed QP or less constrained ABR) to expedite the pass.
    *   **Statistics Collection and Writing**:
        *   After each frame is encoded, `RateCtrl::addRCPassStats` is called, populating a `TRCPassStats` object with actual encoding results (QP used, bits consumed, PSNR, activity measures, etc.).
        *   `RateCtrl::storeStatsData` is then invoked. If `m_rcStatsFHandle` is open for writing (configured via `setRCPass` with `statsFName` and `!rcIsFinalPass`), the `TRCPassStats` for the frame are written as a JSON object to the specified statistics file (`m_RCStatsFileName`). This file accumulates the statistics for the entire sequence.

*   **Subsequent Pass(es) (e.g., Final Pass)**:
    *   **Loading Statistics**:
        *   When `EncLib::initPass` configures `RateCtrl` for the final pass, `RateCtrl::setRCPass` (with `rcIsFinalPass = true` and a valid `statsFName`) calls `openStatsFile` (for reading) and then `readStatsFile`.
        *   `readStatsFile` parses the JSON objects from `m_RCStatsFileName`, reconstructing `TRCPassStats` for each frame and storing them in `m_listRCFirstPassStats`.
    *   **Using Loaded Statistics (`RateCtrl::xProcessFirstPassData`)**:
        *   Once all statistics are loaded, `RateCtrl::xProcessFirstPassData` (called via `processFirstPassData`) processes this complete set of data:
            *   **Scene Cut Detection (`detectSceneCuts`)**: Operates on the full list of frame statistics, allowing for potentially more robust scene cut identification compared to a sliding window. Detected scene cuts lead to `refreshParameters = true` for the respective frames.
            *   **GOP Processing and Bit Scaling (`processGops`)**:
                *   `getAverageBitsFromFirstPass()`: Calculates the average bits per frame consumed across the *entire first pass*.
                *   A global scaling `ratio` is computed: `(double)encRCSeq->targetRate / (encRCSeq->frameRate * bp1pf)`.
                *   The `numBits` (from first pass) for *every frame* in `m_listRCFirstPassStats` is scaled by this `ratio` to determine its initial `targetBits` for the final pass.
                *   `frameInGopRatio` is then calculated for each frame based on these globally scaled target bits and the sum of target bits for its GOP.
                *   If `encRCSeq->maxGopRate` is active, a "pre-capping" step can occur: GOPs exceeding this limit have their total bits reduced, and the saved bits are redistributed to other GOPs, further refining `targetBits` globally.
            *   **Frame-Level QP Determination (`initRateControlPic`)**:
                *   The `targetBits` (now globally scaled and potentially adjusted by pre-capping), `frameInGopRatio`, and other statistics (QP, lambda, `visActY` from the first pass) stored in `TRCPassStats` are used by `initRateControlPic` as described in Section 3.2. The key difference is that these input statistics are now derived from a complete, globally analyzed first pass, rather than a limited lookahead window.
                *   `RateCtrl::getBaseQP()` uses the complete `firstPassData` to estimate a more stable initial QP for the second pass.

*   **Contrast with Lookahead**:
    *   **Scope of Information**: Multi-pass RC has a *global* view of the entire sequence's characteristics from the completed first pass. Lookahead has a *localized window* of future frames.
    *   **Optimization**: Multi-pass allows for more globally optimal bit distribution, as decisions for early parts of the video can be made knowing the demands of later parts. Lookahead optimizes within its window, which is generally very effective but might not achieve the same level of global optimality as a full two-pass approach.
    *   **Latency**: Multi-pass inherently introduces more latency as the entire sequence needs to be processed once before the final pass can begin. Lookahead adds less latency, corresponding to the depth of the lookahead window.
    *   **Use Case**: Multi-pass is often preferred for applications where maximum quality for a given bitrate is paramount and latency is not a primary concern (e.g., offline encoding for VoD). Lookahead is suitable for scenarios requiring lower latency with good quality (e.g., live or near-live encoding).

Both advanced strategies significantly enhance the rate controller's ability to manage bitrate and improve quality compared to a simple single-pass ABR without future frame information.


## 5. HRD Compliance

The Hypothetical Reference Decoder (HRD) is a model specified in video coding standards like H.266/VVC. It defines a hypothetical decoder with specific buffer constraints (Coding Picture Buffer - CPB) and a defined behavior for data removal from these buffers. HRD compliance is crucial for ensuring interoperability and smooth playback of encoded bitstreams across various decoders and platforms. A compliant bitstream guarantees that a decoder adhering to the HRD model will not experience buffer overflow (receiving data faster than it can be processed or buffered) or underflow (data not arriving in time for decoding).

VVenC's rate control mechanism contributes to generating HRD-compliant bitstreams, primarily by managing the output bitrate, while the explicit signaling of HRD parameters is handled by a dedicated module.

*   **HRD-Related Configuration Parameters (`vvencCfg.h`)**:
    The user can influence HRD-related signaling through several parameters in `vvencCfg.h`:
    *   **`m_hrdParametersPresent` (bool)**: If true, this flag enables the signaling of HRD parameters within the Video Usability Information (VUI) part of the Sequence Parameter Set (SPS). These parameters define the characteristics of the HRD model, such as buffer sizes and bitrates, that the stream conforms to.
    *   **`m_bufferingPeriodSEIEnabled` (bool)**: When true, Buffering Period SEI (Supplemental Enhancement Information) messages are included in the bitstream. These SEIs signal initial CPB removal delays, crucial for initializing the HRD buffer at the start of a sequence or after random access.
    *   **`m_pictureTimingSEIEnabled` (bool)**: If true, Picture Timing SEI messages are included. These messages provide information for each access unit, such as its removal time from the CPB and its DPB (Decoded Picture Buffer) output time, which are essential for the HRD's operation.
    *   **Bitrate Configuration (`m_RCTargetBitrate`, `m_RCMaxBitrate`)**: While not HRD parameters themselves, these rate control settings are fundamental. The `m_RCTargetBitrate` is typically used as the nominal bitrate in the HRD parameters signaled in the VUI. `m_RCMaxBitrate` can help constrain peaks.
    *   It's important to note that the actual CPB size (e.g., `cpb_size_value_minus1`) signaled in the VUI is generally not directly configured by a user parameter in `vvencCfg.h` for `RateCtrl`'s use. Instead, it's typically derived from the Profile, Tier, and Level (PTL) of the encoded sequence, as defined by the VVC standard.

*   **Role of `RateCtrl` in HRD Compliance**:
    The `RateCtrl` class does **not** directly model the HRD CPB during its QP determination process. It doesn't explicitly track CPB fullness to make QP decisions based on preventing overflow or underflow of the standard-defined HRD buffer. However, it indirectly supports the generation of an HRD-compliant stream through several mechanisms:
    1.  **Bitrate Adherence**: Its primary goal is to achieve the `m_RCTargetBitrate`. A stable bitrate close to the target is essential for HRD compliance, as the HRD parameters are signaled based on this target.
    2.  **Managing Bitrate Peaks**:
        *   The `m_RCMaxBitrate` configuration parameter is used to calculate `EncRCSeq::maxGopRate`.
        *   `RateCtrl::initRateControlPic` uses `maxGopRate` to cap the `targetBits` allocated to a picture, especially at the beginning of a GOP. This helps prevent excessive bitrate spikes over short periods (like a single GOP), which could lead to CPB overflow.
    3.  **Smoothing QP Variations (`EncRCPic::clipTargetQP`)**:
        *   The `clipTargetQP` function limits how much the QP for a picture can deviate from the QPs of previously coded pictures in the same or lower temporal layers. This helps to avoid drastic changes in picture size from one frame to the next, leading to a smoother bitstream that is easier for the HRD model to manage.
    4.  **Internal Buffer Model**: `RateCtrl` uses an internal model based on `encRCSeq->estimatedBitUsage` (cumulative target bits) and `encRCSeq->bitsUsed` (cumulative actual bits). When `bitsUsed` deviates significantly from `estimatedBitUsage`, `targetBits` for the current picture are adjusted. While this is a general RC buffer model, not a strict HRD CPB model, it serves a similar purpose of reacting to bit production deviations and guiding the rate towards the target, which is beneficial for HRD compliance.

*   **Role of `EncHRD`**:
    The `EncHRD` class (defined in `source/Lib/EncoderLib/EncHRD.h` and `.cpp`) is primarily responsible for **HRD parameter signaling**:
    1.  **Initialization (`EncHRD::initHRDParameters`)**: This function is called during the SPS setup (e.g., in `EncGOP::xInitSPS`). It populates the `GeneralHrdParams` and `OlsHrdParams` structures (members of the `HRD` base class, which `EncHRD` inherits).
        *   It uses `encCfg.m_RCTargetBitrate` as the basis for `bit_rate_value_minus1`.
        *   The `cpb_size_value_minus1` is derived from the PTL of the sequence (via `ProfileLevelTierFeatures::getCpbSizeInBits()`).
        *   Other parameters like `timeScale`, `numUnitsInTick` are derived from frame rate configuration.
        These HRD parameters are then written into the VUI section of the SPS by the `HLSWriter`.
    2.  **SEI Message Generation**: `EncHRD` also plays a role in generating HRD-related SEI messages. For instance, `EncGOP::xWriteLeadingSEIs` calls `m_seiEncoder.initBufferingPeriodSEI`, which in turn populates `m_EncHRD.bufferingPeriodSEI`. This SEI message contains crucial initial delay parameters for the CPB. The Picture Timing SEI messages, also coordinated by `SEIWriter` (often part of `EncGOP`), will reflect the actual access unit sizes produced by the encoder (which are a result of `RateCtrl`'s QP decisions) and their corresponding removal times from the CPB.
    3.  **Implicit Use of `RateCtrl` Output**: While `EncHRD` doesn't directly use `RateCtrl`'s internal state for *calculating* the VUI HRD parameters (which are largely based on configuration and PTL), the SEI messages it helps generate (like Picture Timing) *implicitly* use `RateCtrl`'s output because these SEIs must accurately describe the properties (e.g., size, timing) of the actual bitstream generated under `RateCtrl`'s influence.

In summary, VVenC achieves HRD compliance through a separation of concerns. `RateCtrl` is responsible for producing a bitstream that adheres to the target bitrate and avoids excessive fluctuations, primarily using its own internal models and constraints like `maxGopRate`. `EncHRD` is then responsible for correctly signaling the HRD parameters (based on configuration and PTL) in the VUI and assisting in the generation of SEI messages that describe the properties of this bitstream from an HRD perspective. There is no direct, tight feedback loop where an HRD buffer model within `EncHRD` dynamically adjusts `RateCtrl`'s QPs on a frame-by-frame basis based on HRD buffer fullness. Instead, `RateCtrl`'s success in meeting the target bitrate and managing peaks is the primary factor that enables `EncHRD` to signal valid, compliant HRD information.


## 6. Command-Line Usage for Rate Control Modes (`vvencapp`)

The `vvencapp` command-line application allows users to configure various rate control modes through its options. These options map to members of the `vvenc_config` structure, which is then used to initialize and control the encoder.

1.  **Fixed QP Mode**:
    This mode encodes the entire sequence (or segment) using a fixed Quantization Parameter (QP) for all frames (though GOP structure and QP offsets might still apply). This generally results in a variable bitrate, with quality being relatively constant at the chosen QP level.

    *   **Command-Line Example**:
        ```bash
        vvencapp -i input.yuv --width <W> --height <H> --framerate <FR> --qp 32 --bitrate 0
        ```
        Or, if `--bitrate 0` is the default when `--qp` is specified:
        ```bash
        vvencapp -i input.yuv --width <W> --height <H> --framerate <FR> --qp 32
        ```
    *   **Key `vvenc_config` Parameters**:
        *   `m_QP` (int): Set to the desired fixed QP value (e.g., 32). This is the primary parameter for this mode.
        *   `m_RCTargetBitrate` (int): Must be set to 0 to disable Average Bitrate (ABR) control, thereby enabling fixed QP mode.

2.  **ABR Single-Pass Mode (No Lookahead, No Multi-Pass)**:
    This mode targets a specific average bitrate for the sequence in a single encoding pass, without using lookahead or information from a previous pass. The rate controller adjusts QP frame by frame based on past encoding statistics and its internal models to try and meet the target.

    *   **Command-Line Example**:
        ```bash
        vvencapp -i input.yuv --width <W> --height <H> --framerate <FR> --bitrate 1000000 --lookahead 0 --passes 1
        ```
        (Explicitly setting `--lookahead 0` and `--passes 1` ensures this specific mode, as some presets might enable lookahead by default with ABR).
    *   **Key `vvenc_config` Parameters**:
        *   `m_RCTargetBitrate` (int): Set to the desired target bitrate in bits per second (e.g., 1000000).
        *   `m_RCNumPasses` (int): Should be 1.
        *   `m_LookAhead` (int): Should be 0.

3.  **ABR Two-Pass Mode**:
    This mode involves two encoding passes. The first pass analyzes the video and collects statistics, which are written to a file. The second pass uses these statistics to make more informed rate control decisions, typically resulting in better quality and bitrate adherence.

    *   **Command-Line Examples**:
        *   **First Pass**:
            ```bash
            vvencapp -i input.yuv --width <W> --height <H> --framerate <FR> --bitrate 1000000 --passes 2 --pass 0 --rcstatsfile stats.json
            ```
        *   **Second Pass**:
            ```bash
            vvencapp -i input.yuv --width <W> --height <H> --framerate <FR> --bitrate 1000000 --passes 2 --pass 1 --rcstatsfile stats.json
            ```
    *   **Key `vvenc_config` Parameters**:
        *   `m_RCTargetBitrate` (int): Set to the desired target bitrate (e.g., 1000000) for both passes.
        *   `m_RCNumPasses` (int): Set to 2.
        *   `m_RCPass` (int): Set to 0 for the first pass and 1 for the second pass.
        *   The application internally uses the `--rcstatsfile` argument to manage the statistics file, which corresponds to an internal filename variable often associated with `vvenc_config` or application-level logic.

4.  **ABR Single-Pass with Lookahead**:
    This mode enhances single-pass ABR by enabling a lookahead mechanism. The encoder analyzes a window of upcoming frames to gather statistics about their complexity, motion, and noise levels before they are actually encoded by the main encoding process. This allows for more proactive rate control decisions.

    *   **Command-Line Example**:
        ```bash
        vvencapp -i input.yuv --width <W> --height <H> --framerate <FR> --bitrate 1000000 --lookahead 1
        ```
        (The value for `--lookahead` might specify the depth or simply enable it; '1' typically means enabled with a default depth. This often implies `--passes 1`).
    *   **Key `vvenc_config` Parameters**:
        *   `m_RCTargetBitrate` (int): Set to the desired target bitrate (e.g., 1000000).
        *   `m_LookAhead` (int): Set to a value > 0 to enable lookahead (e.g., 1).
        *   `m_RCNumPasses` (int): Should be 1 (or default to 1 when lookahead is active).

5.  **Enabling Perceptual QP Adaptation (QPA)**:
    Perceptual QPA modulates the QP at a finer granularity (CTU or block level) based on local content characteristics (activity, saliency, noise). It is typically used in conjunction with an ABR mode (either lookahead or two-pass, as QPA benefits greatly from the statistics gathered by these methods).

    *   **Command-Line Example (with Lookahead ABR)**:
        ```bash
        vvencapp -i input.yuv --width <W> --height <H> --framerate <FR> --bitrate 1000000 --lookahead 1 --qpa 1
        ```
        (The value for `--qpa` might enable it or select a specific QPA mode if multiple are available; '1' often means enabled).
    *   **Key `vvenc_config` Parameter**:
        *   `m_usePerceptQPA` (bool): Set to `true` (internally represented, e.g., by a non-zero integer if `--qpa 1` is used) to enable Perceptual QP Adaptation. This is usually combined with settings for an ABR mode.

**Note**: The exact default values for `m_RCNumPasses` and `m_LookAhead` when only `--bitrate` is specified can depend on the `vvencapp` implementation or the chosen preset (via `--preset <mode>`). For instance, the `medium` preset (default) might enable lookahead automatically if a target bitrate is provided. To ensure a specific mode like single-pass ABR *without* lookahead, explicitly setting `--lookahead 0` and `--passes 1` is recommended. The `--rcstatsfile` option is an application-level parameter that tells `vvencapp` where to read/write the statistics file; the filename itself is not directly part of `vvenc_config` but is used by the application to coordinate multi-pass encoding.


## 7. Conclusion

The VVenC encoder implements a comprehensive and flexible rate control system designed to meet diverse encoding needs, from simple constant quality encoding to highly optimized bitrate-constrained scenarios.

VVenC's rate control capabilities can be broadly summarized as follows:
1.  **Fixed QP Mode**: Offers straightforward control for achieving a consistent quality level, with the bitrate adapting to content complexity.
2.  **Average Bitrate (ABR) Modes**: These form the core of its rate control strategies, aiming to achieve a specific target average bitrate.
    *   **Single-Pass ABR**: Provides a basic ABR implementation suitable for scenarios where encoding speed is paramount and some variability in bitrate adherence or quality is acceptable.
    *   **Single-Pass ABR with Lookahead**: Significantly enhances single-pass ABR by incorporating a lookahead mechanism. This allows the encoder to analyze upcoming frames, gather statistics on complexity, motion, and noise, and make proactive adjustments to bit allocation and QP. This generally results in improved quality and more stable bitrate control compared to basic single-pass ABR.
    *   **Multi-Pass ABR (Typically Two-Pass)**: Offers the highest level of bitrate accuracy and quality optimization. By performing a full first pass to gather detailed statistics about the entire sequence, the final encoding pass can make globally optimized decisions regarding bit distribution, leading to very precise bitrate adherence and often the best possible quality for the given target.
3.  **Perceptual QP Adaptation (QPA)**: Can be used in conjunction with ABR modes (especially lookahead or two-pass). QPA refines QP at a more granular level (CTU/block) based on local content characteristics (visual activity, noise, saliency). This aims to improve subjective visual quality by allocating more bits to regions that are more perceptually important or complex.

The interplay between the `RateCtrl` class and its associated data structures (`EncRCSeq`, `EncRCPic`, `TRCPassStats`), along with the encoder's pipelined architecture (`EncLib`, `EncGOP`), enables these sophisticated strategies. The lookahead mechanism, in particular, provides a good balance between encoding efficiency and quality by allowing proactive rate control decisions without the full latency of a separate pass. For scenarios demanding the utmost precision and quality, the two-pass mode remains a powerful option.

In conclusion, VVenC provides a robust and adaptable rate control framework. The choice of which mode and configuration to use will depend on the specific application's requirements, balancing factors such as desired encoding time, the need for strict bitrate adherence (e.g., for streaming), and the pursuit of maximum perceptual quality. Its support for various ABR strategies, enhanced by lookahead and perceptual QPA, makes it a versatile tool for a wide range of video encoding tasks.
