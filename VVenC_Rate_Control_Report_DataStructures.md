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
