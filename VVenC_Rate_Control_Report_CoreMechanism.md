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
