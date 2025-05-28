## 3. Motion Estimation (ME) (`InterSearch`)

Motion Estimation (ME) is the process of finding the optimal Motion Vector (MV) for a given Prediction Unit (PU) by searching a reference picture. The `InterSearch` class in VVenC is primarily responsible for this. The goal is to find an MV that points to a block in a reference picture that is the best match for the current block, typically minimizing a cost function.

*   **Main ME Function**:
    *   `InterSearch::xMotionEstimation(...)`: This is the core function for translational motion estimation. It's called by higher-level functions like `predInterSearch` (which orchestrates tests for different reference pictures/lists).

*   **Integer Pel Search**:
    This stage aims to find the best matching block at full-pixel accuracy within a defined search range.
    *   **Search Algorithms**:
        *   **TZSearch (`InterSearch::xTZSearch`)**: The Test Zone Search is an adaptive fast search algorithm. It starts with initial predictors (AMVP, zero MV, etc.) and iteratively refines the search by testing points in specific patterns (diamond via `xTZ8PointDiamondSearch`, square via `xTZ8PointSquareSearch`, or smaller patterns like `xTZ2PointSearch` for fine-tuning) around the current best point. The step size of the pattern can decrease as the search converges.
            *   Configuration flags like `m_pcEncCfg->m_motionEstimationSearchMethod` (e.g., `VVENC_MESEARCH_DIAMOND_FAST`, `VVENC_MESEARCH_DIAMOND_ENHANCED`), `m_pcEncCfg->m_fastInterSearchMode`, and `m_pcEncCfg->m_bFastMEAssumingSmootherMVEnabled` influence the specific patterns, search rounds, and early termination conditions of TZSearch.
        *   **Full Search (`InterSearch::xPatternSearch`)**: This algorithm exhaustively evaluates all possible integer MV candidates within the defined search range. It is computationally expensive and typically used for highest quality settings or as part of bi-prediction refinement loops.
    *   **Search Range Determination**:
        *   `m_iSearchRange` (from `vvencCfg.m_SearchRange`) provides a base search radius.
        *   `InterSearch::setSearchRange()` can adapt this range (stored in `m_aaiAdaptSR`) based on factors like the temporal distance to the reference picture (POC difference), often making the range larger for more distant references.
        *   `InterSearch::xSetSearchRange()` defines the actual search boundaries (`SearchRange sr`) for the current ME operation, centering the adapted search range around an initial MV predictor (e.g., an AMVP candidate) and clipping it to picture boundaries.
    *   **Cost Function**: The primary cost function for integer pel search is typically the Sum of Absolute Differences (SAD) or Sum of Absolute Transformed Differences (SATD), combined with a rate term for the motion vector difference (MVD).
        *   `m_pcRdCost->setDistParam(...)` is used to configure the distortion calculation (e.g., `DF_SAD`, `DF_HAD_fast`).
        *   `m_pcRdCost->getCostOfVectorWithPredictor(mv.hor, mv.ver, imvShift)` estimates the bits required to signal the MVD (current MV - predicted MV), scaled by lambda.
        *   The search minimizes: `Distortion_Metric (SAD/SATD) + λ_motion * Bits_MVD`.

*   **Fractional Pel Refinement**:
    After the best integer MV is found, it's refined to fractional pixel accuracy (typically quarter-pel for luma in VVC).
    *   **Main Function**: `InterSearch::xPatternSearchFracDIF(...)`.
    *   **Process**: It's a hierarchical process:
        1.  **Half-Pel Refinement**:
            *   `InterPrediction::xExtDIFUpSamplingH()`: Generates half-pel interpolated samples around the best integer MV position using VVC's 8-tap (or reduced tap via `m_pcEncCfg->m_meReduceTap`) interpolation filters (from `InterpolationFilter` class, accessed via `m_if`). These are stored in `m_filteredBlock[verHalf][horHalf][0]`.
            *   `InterSearch::xPatternRefinement()`: Tests the integer position and its 8 surrounding half-pel positions. The cost function is similar to integer search (SAD/SATD + MVD rate). The best half-pel displacement (`rcMvHalf`) is found.
        2.  **Quarter-Pel Refinement**:
            *   If quarter-pel precision is enabled (`cu.imv == IMV_OFF`) and the half-pel search resulted in a non-zero displacement:
            *   `InterPrediction::xExtDIFUpSamplingQ()`: Generates quarter-pel interpolated samples around the best half-pel position, again using VVC interpolation filters. It often selectively generates only the necessary quarter-pel samples based on the best half-pel direction (`patternId` and `s_doInterpQ` table) to save computations.
            *   `InterSearch::xPatternRefinement()`: Tests the best half-pel position and its 8 surrounding quarter-pel positions. The best quarter-pel displacement (`rcMvQter`) is found.
    *   **Interpolation**: The `InterPrediction` class (via its `m_if` member, an `InterpolationFilter` instance) performs the actual sample interpolation using VVC standard-defined filters (e.g., 8-tap for luma half-pel, 7-tap for luma quarter-pel, 4-tap for chroma).
    *   **Cost Function**: Similar to integer search, using SAD/SATD and MVD rate. The lambda scaling (`m_pcRdCost->setCostScale()`) might be adjusted for different refinement stages (e.g., less emphasis on rate for finer refinements).

*   **Bi-prediction ME Strategies**:
    *   When evaluating bi-prediction (`Slice::isInterB()` is true), `EncCu::xCheckRDCostInter` typically calls `InterSearch::xMotionEstimation` iteratively.
    *   **Iterative Refinement**:
        1.  Initially, uni-directional ME is performed for L0 and L1 independently to get `cMv[0]` and `cMv[1]`.
        2.  Then, one MV (e.g., L0's `cMvBi[0]`) is fixed. The original signal is modified by subtracting the L0 prediction (`origBufTmp.removeHighFreq(otherBuf, ...)`).
        3.  ME is performed for L1 against this modified original to find a refined `cMvBi[1]`.
        4.  The roles are swapped: L1's `cMvBi[1]` is fixed, and ME is performed for L0 against `Original - Prediction_L1` to refine `cMvBi[0]`.
        5.  This process can iterate a few times (`iNumIter` in `xCheckRDCostInter`), controlled by settings like `m_pcEncCfg->m_fastInterSearchMode`.
    *   **Symmetrical MVD (SMVD)**: If enabled (`m_pcEncCfg->m_SMVD`), `InterSearch::xSymMotionEstimation` performs a specialized search. It evaluates MVs where L0 and L1 MVs are symmetrical (opposite directions, same magnitude) or differ by a small, explicitly signaled MVD.
    *   **Weighted Prediction (BCW)**: When BCW is active (`cu.BcwIdx != BCW_DEFAULT`), `InterSearch::xGetMEDistortionWeight()` provides a weight `fWeight`. This weight is applied to the distortion term during bi-predictive ME: `floor(fWeight * (double)ruiCost - ...)`. This gives different emphasis to the match quality from one reference list when refining the MV for the other.

*   **AMVP (Advanced Motion Vector Prediction)**:
    AMVP is used to predict the current MV, and only the difference (MVD) is coded.
    *   **Candidate Generation (`CU::fillMvCand`)**: This static function (typically in `UnitTools.cpp`) is called by `InterSearch::xEstimateMvPredAMVP`. It generates a list of AMVP candidates by checking:
        *   Spatial neighbors (left, above, corners of the current PU).
        *   Temporal co-located MVs from reference pictures.
        *   The candidates are stored in an `AMVPInfo` structure.
    *   **Usage in ME**:
        *   **Initial Predictor**: `xEstimateMvPredAMVP` tests these AMVP candidates (using template matching with SAD cost) and selects the best one (`rcMvPred`, `riMVPIdx`) to serve as the starting point and predictor for the main integer and fractional ME search.
        *   **MVD Costing**: Throughout ME, the cost of signaling the MVD (`current_MV - rcMvPred`) is added to the distortion cost.
    *   **Best MVP Index Selection (`xCheckBestMVP`)**: After the final MV (integer + fractional) is determined, this function re-evaluates which of the AMVP candidates, when used as a predictor for this final MV, would result in the fewest bits for signaling both the MVD and the MVP index. This doesn't change the MV itself, only its coded representation.
    *   **`m_auiMVPIdxCost`**: A pre-calculated table storing the bit costs for signaling different MVP indices based on the number of available candidates.

The `InterSearch` module thus combines fast search algorithms, hierarchical refinement, and sophisticated predictor selection (AMVP) to efficiently find motion vectors that provide a good balance between prediction accuracy and coding cost.Okay, I will continue generating the sections for the "VVenC Inter Prediction Analysis Report".

**Step 4: Generate Section 4 - Motion Compensation (MC) (`InterPrediction`)**
