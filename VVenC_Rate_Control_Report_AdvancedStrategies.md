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
