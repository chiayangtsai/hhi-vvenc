# VVenC Inter Prediction: Algorithms and Mechanisms

## 1. Introduction

Inter-frame prediction, or simply inter prediction, is a cornerstone of modern video compression standards, including H.266/VVC. Its primary role is to exploit temporal redundancy between successive frames in a video sequence. Instead of encoding each frame independently (as in intra prediction), inter prediction allows blocks of pixels in the current frame to be predicted from already coded and reconstructed blocks in previously coded frames (reference frames). This is achieved by estimating motion (Motion Estimation - ME) to find the best matching block in a reference frame and then encoding the motion vector (MV) and the residual (the difference between the original block and the predicted block). By encoding only the motion and residual, significant compression efficiency is achieved, especially in sequences with moderate to high motion.

The VVenC encoder implements a comprehensive and highly sophisticated suite of inter prediction tools as specified by the VVC standard. These tools range from traditional block-based translational motion models to more complex affine and geometric partitioning modes, along with advanced techniques for motion vector prediction and refinement. This report aims to provide a detailed explanation of these inter prediction mechanisms within VVenC, targeting software engineers familiar with general video coding concepts. We will explore the key algorithms, data structures, and the overall workflow involved in making inter prediction decisions.


## 2. Key Classes and Data Structures

VVenC's inter prediction relies on a set of core classes for its algorithmic logic and various data structures to store and manage motion information, reference picture details, and mode decisions.

*   **Main Classes**:
    *   **`InterSearch`** (`source/Lib/EncoderLib/InterSearch.h/.cpp`): This class is central to motion estimation (ME). It implements algorithms for finding optimal motion vectors (MVs) for translational, affine, and other motion models. It also handles the derivation of merge candidates.
    *   **`InterPrediction`** (`source/Lib/CommonLib/InterPrediction.h/.cpp`): Responsible for generating the actual predicted block (Motion Compensation - MC) once the motion vectors and reference pictures are determined. It utilizes interpolation filters for fractional MV precision.
    *   **`InterpolationFilter`** (`source/Lib/CommonLib/InterpolationFilter.h/.cpp`): Provides functions for interpolating fractional pixel positions from reference picture samples, crucial for sub-pel accurate MC.
    *   **`AffineGradientSearch`** (Likely part of `InterSearch` or a utility it uses): Handles the gradient-based search for refining affine motion vectors.
    *   **`EncCu`** (`source/Lib/EncoderLib/EncCu.h/.cpp`): Manages the encoding process for a Coding Unit (CU). It makes decisions on whether to use inter or intra prediction and, if inter, invokes `InterSearch` and `InterPrediction` to evaluate various inter modes.
    *   **`EncModeCtrl`** (`source/Lib/EncoderLib/EncModeCtrl.h/.cpp`): Controls the overall mode decision process, including CU partitioning and pruning of inter/intra modes to be tested, based on encoder settings and RD cost.
    *   **`Slice`** (`source/Lib/CommonLib/Slice.h`): Represents a slice and contains slice-level information, including reference picture lists (RPLs) and weighting parameters for bi-prediction.
    *   **`Picture`** (`source/Lib/CommonLib/Picture.h`): Represents a decoded or reconstructed picture, used as a reference for inter prediction. It provides access to reconstructed sample data.
    *   **`CodingUnit` (CU)** (`source/Lib/CommonLib/Unit.h`): Stores the final encoding decisions for a CU, including inter prediction mode, MVs, reference indices, merge flags, etc.
    *   **`PredictionUnit` (PU)** (`source/Lib/CommonLib/Unit.h`): While VVC often integrates PU concepts directly into the CU, the motion information (MVs, refIdx) is logically associated with prediction units or sub-blocks within a CU.
    *   **`CodingStructure` (CS)** (`source/Lib/CommonLib/CodingStructure.h`): A container for CUs, PUs, and TUs for a specific region (e.g., a CTU or a CU undergoing recursive splitting). It provides context, such as access to neighboring CUs for deriving motion predictors.

*   **Key Data Structures for Inter Prediction**:
    *   **`Mv`** (Motion Vector, `source/Lib/CommonLib/MotionInfo.h`):
        *   Represents a 2D motion vector with `hor` (horizontal) and `ver` (vertical) components.
        *   Includes methods for precision handling (e.g., converting between integer, half-pel, quarter-pel, and internal higher precision).
    *   **`MvField`** (`source/Lib/CommonLib/MotionInfo.h`):
        *   Combines an `Mv` with its corresponding `refIdx` (reference picture index). Used extensively in candidate lists.
    *   **`MotionInfo`** (`source/Lib/CommonLib/MotionInfo.h`):
        *   Stores motion information for a block, typically for each prediction list (L0, L1). Includes `mv[2]` and `refIdx[2]`. Often used for the smallest 4x4 sub-blocks in advanced motion models like affine or GPM.
    *   **Reference Picture List (RPL) Structures**:
        *   `ReferencePictureList` (in `Slice.h`): Defines a list of reference pictures, including their POCs (`m_refPicIdentifier`).
        *   `Slice::m_RPL0`, `Slice::m_RPL1`: Arrays storing the active RPLs for the current slice.
        *   `Picture` objects themselves serve as the reference data.
    *   **`CodingUnit` Inter-Prediction Fields**:
        *   `mergeFlag` (bool): True if merge mode is used.
        *   `mergeIdx` (uint): Index of the selected merge candidate.
        *   `mmvdMergeFlag` (bool), `mmvdMergeIdx` (uint): For Merge with MVD (MMVD).
        *   `geoFlag` (bool), `geoSplitDir` (uint8_t), `geoMergeIdx[2]` (uint8_t): For Geometric Partitioning Mode (GPM).
        *   `interDir` (uint8_t): Inter prediction direction (1 for L0, 2 for L1, 3 for Bi-pred).
        *   `mvpIdx[NUM_REF_PIC_LIST_01]` (int8_t): Index of the AMVP candidate used for MVD prediction.
        *   `mvd[NUM_REF_PIC_LIST_01][MAX_NUM_PARTS_IN_CTU]` (Mv): Motion Vector Difference.
        *   `mv[NUM_REF_PIC_LIST_01][MAX_NUM_PARTS_IN_CTU]` (Mv): Final Motion Vector.
        *   `refIdx[NUM_REF_PIC_LIST_01]` (int8_t): Reference picture index for L0 and L1.
        *   `affine` (bool): True if affine prediction is used.
        *   `affineType` (EAffineModel): Type of affine model (4-parameter or 6-parameter).
        *   `imv` (uint8_t): Specifies MV precision (0 for quarter-pel, 1 for integer-pel MVD for half-pel MV, 2 for 4-pel MVD).
        *   `sbtInfo` (uint8_t): Information for Sub-Block Transform, relevant if residual coding is tied to inter modes.
        *   `BcwIdx` (uint8_t): Index for Bi-directional Optical Flow (BDOF) or Bi-directional Chroma Weighting (BCW).
        *   `smvdMode` (uint8_t): Symmetrical MVD mode flag.
        *   `ciipFlag` (bool): True if Combined Inter-Intra Prediction (CIIP) is used.
    *   **Merge Candidate Structures (primarily in `EncCu.cpp` and `InterSearch.cpp`)**:
        *   `MergeCtx`: Holds regular spatial and temporal merge candidates, MMVD candidates.
        *   `AffineMergeCtx`: Holds affine merge candidates, including SbTMVP.
        *   `EncCu::MergeItem` / `MergeItemList`: Internal structures in `EncCu` used during RDO to store, sort, and prune evaluated merge/affine/GPM candidates along with their costs and prediction buffers.
        *   `GeoMergeCombo` / `GeoComboCostList`: Used by `EncCu` to manage and sort GPM candidates.
    *   **AMVP Structures (`InterSearch.h`, `Mv.h`)**:
        *   `AMVPInfo`: Stores translational AMVP candidates (`mvCand[]`) and their count (`numCand`).
        *   `AffineAMVPInfo`: Stores affine AMVP candidates (e.g., `mvCandLT[]`, `mvCandRT[]`, `mvCandLB[]`).
    *   **HMVP (History-based Motion Vector Prediction) Structures**:
        *   `HPMVInfo` (in `MotionInfo.h`): Stores motion information for HMVP.
        *   `LutMotionCand` (`CodingStructure::motionLut`): Lookup table within `CodingStructure` storing recently used MVs for HMVP.
    *   **Specialized Tool Storage**:
        *   `InterSearch::BlkUniMvInfoBuffer`: Caches uni-directional MVs for potential reuse, e.g., in bi-prediction or other modes.
        *   `AffineProfList`: Caches affine motion models for reuse.
        *   `InterSearch::m_acBVs`: Stores IBC candidate block vectors.
        *   `InterPrediction::m_yuvPred[2]`, `m_geoPartBuf[2]`, `m_IBCBuffer`: Buffers used by `InterPrediction` to store generated prediction signals for L0/L1, GPM partitions, and IBC reference blocks respectively.
        *   `InterPrediction::m_filteredBlock`, `m_filteredBlockTmp`: Buffers for storing sub-pel interpolated reference samples.
        *   `InterPrediction::m_gradX0/1`, `m_gradY0/1`: Buffers for storing gradients in BDOF.

These classes and structures collectively provide the framework for VVenC to perform complex motion estimation, generate predictions, and make efficient inter mode decisions.


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

The `InterSearch` module thus combines fast search algorithms, hierarchical refinement, and sophisticated predictor selection (AMVP) to efficiently find motion vectors that provide a good balance between prediction accuracy and coding cost.


## 4. Motion Compensation (MC) (`InterPrediction`)

Motion Compensation (MC) is the process of generating a predicted block of pixels using the motion vectors (MVs) and reference picture indices determined during Motion Estimation (ME). The `InterPrediction` class in VVenC is primarily responsible for these operations.

*   **Main MC Function**:
    *   **`InterPrediction::motionCompensation(CodingUnit& cu, PelUnitBuf& predBuf, const RefPicList& refPicList = REF_PIC_LIST_X, PelUnitBuf* predBufDfltWght = nullptr)`**: This is the top-level function called by `EncCu` (or `InterSearch` during its internal RDO evaluations) to generate the final prediction signal for a Coding Unit (`cu`) and store it in `predBuf`.
        *   If `refPicList` is specified (L0 or L1), it calls `xPredInterUni` for uni-directional prediction.
        *   If `refPicList == REF_PIC_LIST_X` (indicating bi-prediction or selection between L0/L1 for uni-pred has already happened and MVs are set in `cu`), it handles various cases:
            *   **Identical Motion (`xCheckIdenticalMotion`)**: If L0 and L1 MVs and reference pictures are identical (and no weighted prediction), it performs uni-prediction using L0.
            *   **DMVR (`CU::checkDMVRCondition`, `xProcessDMVR`)**: If Decoder-side Motion Vector Refinement (DMVR) is applicable and enabled, `xProcessDMVR` is called to refine MVs for sub-blocks and generate the prediction.
            *   **BDOF (`cu.cs->sps->BDOF`, `xApplyBDOF`)**: If Bi-directional Optical Flow (BDOF) is applicable, `xPredInterBi` will generate initial L0/L1 predictions, and then `xApplyBDOF` refines the combined prediction using image gradients.
            *   **Sub-PU MC (`cu.mergeType != MRG_TYPE_DEFAULT_N && cu.mergeType != MRG_TYPE_IBC`)**: For modes like affine or GPM with sub-block granularity, `xSubPuMC` is called to perform MC for each sub-block.
            *   **Standard Bi-prediction (`xPredInterBi`)**: For regular bi-prediction.
            *   **Intra Block Copy (IBC)**: If `CU::isIBC(cu)`, then `motionCompensationIBC` is called.

*   **Uni-directional Prediction (`xPredInterUni`)**:
    *   **`InterPrediction::xPredInterUni(const CodingUnit &cu, const RefPicList &refPicList, PelUnitBuf &pcYuvPred, const bool bi, const bool bdofApplied)`**: This function generates the prediction for a single reference list (L0 or L1).
    *   It retrieves the MV (`cu.mv[refPicList][0]`) and reference index (`cu.refIdx[refPicList]`).
    *   For each component (Y, Cb, Cr):
        *   It calls **`InterPrediction::xPredInterBlk(...)`**.

*   **Core Block Prediction (`xPredInterBlk`)**:
    *   **`InterPrediction::xPredInterBlk(const ComponentID compID, const CodingUnit &cu, const Picture *refPic, const Mv &_mv, PelUnitBuf &dstPic, const bool bi, const ClpRng &clpRng, const bool bdofApplied, const bool isIBC, const RefPicList refPicList, const SizeType dmvrWidth, const SizeType dmvrHeight, const bool bilinearMC, const Pel *srcPadBuf, const int32_t srcPadStride)`**: This is the workhorse for generating a predicted block for a single component.
    *   **Fractional MV Handling**:
        *   The MV (`_mv`) is decomposed into integer-pel and fractional-pel components.
        *   `xFrac = mv.hor & ((1 << shiftHor) - 1)`
        *   `yFrac = mv.ver & ((1 << shiftVer) - 1)`
    *   **Reference Sample Fetching**:
        *   Calculates the starting position in the reference picture (`refPic`) based on the current block's position and the integer part of the MV.
        *   `refBufPtr` points to these integer-pel reference samples.
    *   **Interpolation (`InterpolationFilter` - `m_if`)**:
        *   **No Fractional Part (`xFrac == 0 && yFrac == 0`)**: Direct copy of reference samples.
        *   **Horizontal Only (`yFrac == 0`)**: `m_if.filterHor(...)` is called.
        *   **Vertical Only (`xFrac == 0`)**: `m_if.filterVer(...)` is called.
        *   **Both Horizontal and Vertical**:
            *   For small blocks (e.g., 4x4, 8x8, 16x16), specialized combined 2D filtering functions like `m_if.filter4x4()`, `m_if.filter8x8()`, `m_if.filter16x16()` might be called.
            *   For other cases, a two-step process is used:
                1.  `m_if.filterHor(...)` creates an intermediate horizontally interpolated block (stored in `m_filteredBlockTmp`).
                2.  `m_if.filterVer(...)` is then applied to this intermediate block to get the final prediction.
        *   The `InterpolationFilter` class implements the VVC standard's interpolation filters (e.g., 8-tap for luma half-pel, 7-tap for luma quarter-pel, 4-tap for chroma). The specific filter phase is determined by `xFrac` and `yFrac`.
        *   `useAltHpelIf` (derived from `cu.imv == IMV_HPEL`) selects alternative half-pel filters if that IMV mode is active.
        *   `bilinearMC` flag can force bilinear interpolation, used in DMVR's initial steps.
    *   **BDOF Handling**: If `bdofApplied` is true (and it's luma), the output of the interpolation is wider/taller to include border samples needed for subsequent gradient calculation in BDOF. The actual prediction is stored in `m_filteredBlockTmp` for BDOF.
    *   **Output**: The interpolated prediction is written to `dstPic.bufs[compID]`.

*   **Bi-directional Prediction (`xPredInterBi` and `xWeightedAverage`)**:
    *   **`InterPrediction::xPredInterBi(const CodingUnit& cu, PelUnitBuf& yuvPred, const bool bdofApplied, PelUnitBuf *yuvPredTmp)`**:
        1.  Calls `xPredInterUni` for L0 to generate `puBuf[L0]`.
        2.  Calls `xPredInterUni` for L1 to generate `puBuf[L1]`.
        3.  Calls `xWeightedAverage` to combine `puBuf[L0]` and `puBuf[L1]` into `yuvPred`.
    *   **`InterPrediction::xWeightedAverage(const CodingUnit& cu, const CPelUnitBuf& pcYuvSrc0, const CPelUnitBuf& pcYuvSrc1, PelUnitBuf& pcYuvDst, const bool bdofApplied, PelUnitBuf* yuvPredTmp)`**:
        *   **Default (No BCW)**: If `cu.BcwIdx == BCW_DEFAULT` (or if other conditions like CIIP apply), it performs a simple average:
            `pcYuvDst.addAvg(pcYuvSrc0, pcYuvSrc1, clpRngs, ...)` which calculates `(L0 + L1 + 1) >> 1`.
        *   **BCW (Bi-directional Chroma Weighting / Weighted Prediction)**: If `cu.BcwIdx != BCW_DEFAULT`, it performs weighted averaging:
            `pcYuvDst.addWeightedAvg(pcYuvSrc0, pcYuvSrc1, clpRngs, cu.BcwIdx, ...)`
            The weights `w0, w1` are derived from `cu.BcwIdx` using `Slice::getWpScaling(REF_PIC_LIST_0/1, cu.refIdx[0/1], &wp_l0/1)` and `g_BcwWeightBase` (typically 128 or 1/2). The formula is `(w0*L0 + w1*L1 + round_offset) >> shift`.
        *   **BDOF Application**: If `bdofApplied` is true (and it's luma), `xApplyBDOF` is called *after* the initial averaging (or weighted averaging if BCW is default). `xApplyBDOF` uses the L0 and L1 predictions (stored in `m_filteredBlockTmp` during `xPredInterUni`) and their gradients to calculate an optical flow based correction, which is then added to the initial averaged prediction.

*   **Intra Block Copy (IBC) (`xIntraBlockCopyIBC` and `motionCompensationIBC`)**:
    *   **`InterPrediction::motionCompensationIBC(CodingUnit& cu, PelUnitBuf& predBuf)`**: Calls `xPredInterUni` with `REF_PIC_LIST_0` and `isIBC=true`.
    *   **`InterPrediction::xPredInterBlk` (for IBC)**:
        *   The reference picture (`refPic`) is the current picture (`cu.slice->pic`).
        *   The MV is the block vector (BV). Since BVs are integer-pel, `xFrac` and `yFrac` are 0.
        *   Instead of fetching from the main reconstructed picture buffer, samples are copied from a local CTU buffer (`m_IBCBuffer`) which stores previously reconstructed blocks within the current CTU (or a limited region).
        *   `InterPrediction::xIntraBlockCopyIBC` performs this copy from `m_IBCBuffer` to `predBuf`, handling potential wrap-around if the source region crosses the buffer boundary.

*   **Affine Prediction (`xPredAffineBlk`)**:
    *   This function is called for affine MC.
    *   It calculates per-sub-block MVs based on the CU's affine control point MVs (`_mv[0]`=LT, `_mv[1]`=RT, `_mv[2]`=LB for 6-param).
        *   `iDMvHorX = (mvRT - mvLT).hor * (1 <<(iBit - Log2(cxWidth)));` (and similar for other MV delta components).
        *   For each sub-block (typically 4x4 or 8x8), an MV is derived using these deltas and the sub-block's position relative to the CU's top-left corner.
    *   For each sub-block, it then calls the standard fractional pixel interpolation (`m_if.filterHor`, `m_if.filterVer`, `m_if.filter4x4`) using the derived sub-block MV and writes the result to the corresponding part of `dstPic`.
    *   **PROF (Prediction Refinement with Optical Flow)**: If enabled (`sps.PROF`), after the initial affine prediction for a sub-block, it can be further refined.
        *   Gradients (`m_gradBuf`) of the initial prediction are calculated (`xFpProfGradFilter`).
        *   `xFpApplyPROF` then applies these gradients and the affine motion model's derivative terms (`dMvScaleHor`, `dMvScaleVer`) to refine the predicted samples.

*   **DMVR (Decoder-side Motion Vector Refinement)**:
    *   **`DMVR::xProcessDMVR(...)`**:
        1.  Pads the L0 and L1 initial prediction regions (`xCopyAndPad`) into `m_yuvPad[L0/L1]`. This padding is needed for the sub-pixel ME search.
        2.  Iteratively refines MVs for sub-blocks (typically 16x16 within a larger PU). For each sub-block:
            *   Performs a local search around the initial (merged) MV for L0 and L1 against their respective padded reference areas. This search often involves SAD calculations at integer-pel positions.
            *   `xSubPelErrorSrfc` can be used to estimate a sub-pel correction based on SADs at surrounding integer positions.
            *   The MVDs for L0 (`cu.mvdL0SubPu`) are updated. L1 MVs are derived symmetrically from L0 MVs relative to the original merge MVs.
        3.  **Final MC (`xFinalPaddedMCForDMVR`)**: After MVs for all sub-blocks are refined, this function performs the final motion compensation for each sub-block using its refined MVs (L0 and L1), writing into temporary buffers `predBuf[L0/L1]`.
        4.  The L0 and L1 predictions are then averaged (`xWeightedAverage`) into `pcYuvDst`.

This detailed process ensures that for any given inter mode and its associated motion parameters, an accurate prediction block is generated, forming the basis for residual calculation and subsequent encoding steps.


## 5. Inter Mode Decision (`EncCu` with `InterSearch` and `EncModeCtrl`)

The process of deciding which inter prediction mode to use for a Coding Unit (CU), along with its associated motion parameters (MVs, reference indices, etc.), is managed by the `EncCu` class, with significant contributions from `InterSearch` (for motion estimation and candidate evaluation) and `EncModeCtrl` (for guiding and pruning the search). The overarching goal is to select the mode that minimizes a Rate-Distortion (RD) cost.

*   **Goal: Minimizing Rate-Distortion (RD) Cost**:
    The fundamental principle behind mode decision is to find the best balance between the distortion (error) of the predicted block compared to the original, and the rate (number of bits) required to signal the chosen mode and its parameters, including any residual information.
    *   **RD Cost Formula**: `Cost = Distortion + λ * Rate`
        *   `Distortion`: Typically Sum of Squared Errors (SSE) for final decisions, or Sum of Absolute Differences (SAD)/Sum of Absolute Transformed Differences (SATD) for faster intermediate evaluations during ME.
        *   `Rate`: The estimated number of bits to encode the mode information, MVs (or MVDs), reference indices, merge indices, and the quantized residual coefficients.
        *   `λ` (Lambda): A Lagrange multiplier that controls the trade-off between rate and distortion. It is derived from the CU's Quantization Parameter (QP).
    *   The `RdCost` class (`m_cRdCost` in `EncCu`) provides methods to calculate distortion and the overall RD cost.

*   **Orchestration by `EncCu::xCompressCU`**:
    This function recursively processes a CU area, deciding whether to code it as a single unit or split it further. For each CU/partition, it evaluates various coding modes. If inter modes are being considered (not an I-slice, not constrained intra):
    *   It calls specific functions to test different categories of inter modes.
    *   It maintains `bestCS` (best `CodingStructure` found so far) and `tempCS` (for testing the current mode).
    *   `EncModeCtrl::tryMode(...)` is called before testing a mode category to see if it should be skipped based on heuristics or configuration.
    *   `EncCu::xCheckBestMode(...)` (which internally calls `EncModeCtrl::useModeResult(...)`) is used after a mode is evaluated to compare its RD cost with the current best and update `bestCS` if the new mode is better.

*   **Evaluation of Standard Inter Modes (AMVP-based)**:
    *   **Function**: `EncCu::xCheckRDCostInter(...)` and `EncCu::xCheckRDCostInterIMV(...)` (for different IMV resolutions).
    *   **Process**:
        1.  **Motion Estimation (`InterSearch::predInterSearch`)**:
            *   For each reference picture in L0 and L1 (and combinations for bi-prediction):
                *   `InterSearch::xMotionEstimation` is invoked to find the best MV, reference index, and AMVP predictor. This involves integer and fractional pel ME.
                *   The cost returned by `xMotionEstimation` is typically `Distortion_ME + λ * Rate_MVD_MVPidx`.
        2.  **Store Uni-directional Results**: The best uni-directional MVs and costs are stored (e.g., in `cMv[L0/L1]`, `uiCost[L0/L1]`). These can be reused for constructing bi-prediction candidates.
        3.  **Bi-prediction Evaluation**:
            *   Iterative refinement: Test L0 with best L1 fixed, then L1 with best L0 fixed.
            *   Test SMVD (Symmetrical MVD) if enabled.
        4.  **Motion Compensation and Residual Coding**:
            *   For the best MV(s) found for uni-L0, uni-L1, and bi-prediction:
                *   `InterPrediction::motionCompensation` generates the predicted block.
                *   `InterSearch::encodeResAndCalcRdInterCU` is called:
                    *   Calculates the residual (Original - Prediction).
                    *   Performs transform and quantization (`m_pcTrQuant->transformNxN`).
                    *   Estimates bits for all syntax elements (MVs, ref_idx, MVD, CBF, coefficients) using `m_CABACEstimator`.
                    *   Calculates distortion (SSE) of the reconstructed block.
                    *   Computes the final RD cost.
        5.  **Update Best**: The mode (L0, L1, or Bi with specific MVs/refs) with the lowest RD cost is compared with `bestCS`.

*   **Evaluation of Merge Modes (including MMVD, SbTMVP, CIIP, GPM, Affine Merge)**:
    *   **Function**: `EncCu::xCheckRDCostUnifiedMerge(...)`.
    *   **Process**:
        1.  **Candidate List Generation**:
            *   Regular Merge candidates (`CU::getInterMergeCandidates`): Spatial, temporal, HMVP, pairwise-averaged.
            *   MMVD candidates (`CU::getInterMMVDMergeCandidates`): Regular merge candidates + pre-defined MVDs.
            *   Affine Merge candidates (`CU::getAffineMergeCand`): Includes SbTMVP if enabled.
            *   GPM candidates (`CU::getGeoMergeCandidates`, `EncCu::prepareGpmComboList`): Combinations of two regular merge candidates with geometric splits.
        2.  **SATD-based Pruning (First Pass in `xCheckRDCostUnifiedMerge`)**:
            *   Functions like `addRegularCandsToPruningList`, `addCiipCandsToPruningList`, etc., are called.
            *   For each candidate in these extended lists:
                *   `EncCu::generateMergePrediction` is called to create the luma prediction.
                *   `EncCu::calcLumaCost4MergePrediction` computes a cost using SAD/SATD and estimated bits for signaling the merge index/type.
            *   Candidates are stored in `m_mergeItemList` and sorted.
            *   The list is pruned based on these costs and fast merge heuristics (`m_pcEncCfg->m_useFastMrg`), limiting the number of candidates (`numMergeSatdCand`) for full RDOQ.
        3.  **Full RDOQ (Second Pass in `xCheckRDCostUnifiedMerge`)**:
            *   Iterates through the pruned `m_mergeItemList`.
            *   For each candidate:
                *   Sets CU motion info using `MergeItem::exportMergeInfo()`.
                *   `EncCu::generateMergePrediction` performs MC for luma and chroma.
                *   `InterSearch::encodeResAndCalcRdInterCU` handles residual coding, full RD cost calculation.
                *   The RD cost is compared with `bestCS`.
            *   **No Residual Check**: For each candidate, a pass with `skipResidual = true` (forcing no residual) is also typically evaluated to see if a SKIP or merge-without-residual mode is optimal.

*   **Skip Mode**:
    *   Skip mode is a special case of merge mode where a merge candidate is chosen, its MVs are used, the MVD is zero, and the residual is also zero (rootCbf is false).
    *   It's evaluated within `xCheckRDCostUnifiedMerge`. When `InterSearch::encodeResAndCalcRdInterCU` is called with `skipResidual = true` (or if the normal residual coding results in `cu.rootCbf = false`), and the RD cost (which then only includes bits for signaling the merge index and skip flags) is the best, skip mode is chosen.
    *   `cu.skip` is set to true if `cu.mergeFlag` is true and `cu.rootCbf` is false.

*   **Role of `RdCost` (`m_cRdCost`)**:
    *   `m_cRdCost.setLambda()`: Sets the Lagrange multiplier based on QP.
    *   `m_cRdCost.setDistortionWeight()`: Sets weights for chroma distortion relative to luma.
    *   `m_cRdCost.getDistPart()`: Calculates distortion (SAD, SATD, SSE).
    *   `m_cRdCost.getCostOfVectorWithPredictor()`: Estimates bits for MVDs.
    *   `m_cRdCost.calcRdCost(bits, distortion)`: Computes the final RD cost.
    *   It also handles cost calculations considering luma reshaping if enabled.

The decision process is hierarchical, with `EncCu::xCompressCU` trying different partitioning (splits). For each partition, it calls these mode evaluation functions. The results (best mode and its RD cost) are propagated up the recursion tree, and the partitioning that leads to the overall minimum RD cost for the original CU area is selected. Fast algorithms and pruning strategies in `EncModeCtrl` are essential to navigate this large search space efficiently.


## 6. Advanced Inter Prediction Tools

VVenC implements a rich set of advanced inter prediction tools beyond basic translational motion models to further improve compression efficiency. These tools provide more flexible ways to predict a block, often by considering more complex motion or by combining predictors.

*   **Merge Modes (Detailed)**:
    Merge mode allows a PU to inherit its motion information (MVs, reference indices, prediction direction) directly from a neighboring PU (spatial merge) or a co-located PU in a reference picture (temporal merge/HMVP). This significantly reduces signaling overhead.
    *   **Candidate Derivation (`CU::getInterMergeCandidates`, `CU::getInterMMVDMergeCandidates`)**:
        *   **Spatial Merge Candidates**: Derived from already coded and reconstructed neighboring blocks (left, above, top-right, bottom-left, above-left).
        *   **Temporal Merge Candidates (HMVP - History-based Motion Vector Prediction)**: Derived from co-located blocks in reference pictures. `CodingStructure::motionLut` stores recently used MVs (HMVP candidates) that can be fetched.
        *   **Pairwise Averaged Candidates**: If multiple spatial/temporal candidates are available, new candidates can be generated by averaging pairs of them.
        *   **Zero MV Candidate**: A candidate with zero MVs is often implicitly or explicitly considered.
        *   **MMVD (Merge with MVD)**: If enabled (`sps.MMVD`), the regular merge candidate list is extended. For each base merge candidate, MMVD applies a set of pre-defined, small MVDs (different step sizes and directions) to generate additional motion hypotheses. This allows for slight refinements over the base merge candidate without explicitly signaling a full MVD.
        *   **SbTMVP (Sub-block Temporal Motion Vector Prediction)**: If affine merge is enabled (`sps.SbtMvp`), SbTMVP candidates are considered. These are a form of affine merge where motion vectors for sub-blocks are derived from co-located temporal blocks, effectively capturing localized motion variations. These are added to the `AffineMergeCtx`.
    *   **Pruning and Signaling**:
        *   The generated list of merge candidates (including MMVD, SbTMVP if applicable) is often pruned to a smaller set (e.g., up to `MRG_MAX_NUM_CANDS`).
        *   In `EncCu::xCheckRDCostUnifiedMerge`, these candidates undergo a SATD-based pre-selection (`m_mergeItemList`) before full RDOQ.
        *   The encoder signals a `merge_idx` to indicate which candidate from the final list is used. If MMVD is used, additional syntax (`mmvd_merge_idx`) signals the base merge candidate and the applied MVD.

*   **Affine Prediction**:
    Affine motion models can represent more complex movements like rotation, scaling, and shearing, which simple translational MVs cannot.
    *   **Model Types (`cu.affineType`)**:
        *   **4-parameter Model (`AFFINEMODEL_4PARAM`)**: Represents translation, rotation, and scaling (aspect ratio preserved). Defined by two control point MVs (CPMV_LT, CPMV_RT).
        *   **6-parameter Model (`AFFINEMODEL_6PARAM`)**: A more general affine model allowing shearing. Defined by three control point MVs (CPMV_LT, CPMV_RT, CPMV_LB).
    *   **Motion Estimation (`InterSearch::xPredAffineInterSearch`, `InterSearch::xAffineMotionEstimation`)**:
        *   **Control Point MV (CPMV) Estimation**: The MVs for the control points (e.g., top-left, top-right, bottom-left corners of the CU) are estimated. This often involves:
            *   Deriving initial CPMV predictors from an affine AMVP list (`CU::fillAffineMvpCand` via `xEstimateAffineAMVP`).
            *   Refining these CPMVs iteratively using a gradient-based search. `InterSearch::xAffineMotionEstimation` calculates the error surface (e.g., difference between original and predicted) and its derivatives with respect to the CPMVs, then solves a system of linear equations (`solveEqual`) to find updates for the CPMVs.
    *   **Affine Merge (`CU::getAffineMergeCand`)**:
        *   Affine motion information can also be inherited from neighboring blocks via affine merge candidates. This includes spatial affine candidates and SbTMVP.
        *   These are evaluated within `EncCu::xCheckRDCostUnifiedMerge` via `addAffineCandsToPruningList`.
    *   **Motion Compensation (`InterPrediction::xPredAffineBlk`)**:
        *   Once the CPMVs are determined, the MV for each sub-block (typically 4x4) within the CU is derived by applying the affine transformation.
        *   `InterPrediction` then performs MC for each sub-block using its derived MV and standard fractional pixel interpolation.
    *   **Signaling**: Affine mode is signaled with flags indicating its use, type (4/6-param), and the MVDs for the CPMVs (if not in merge mode) or the affine merge index.

*   **Geometric Partitioning Mode (GPM)**:
    GPM allows a CU to be partitioned into two regions using one of several pre-defined geometric patterns (e.g., diagonal, horizontal/vertical splits at different locations). Each region is then predicted using independent motion information derived from regular merge candidates.
    *   **Partitioning**: The VVC standard defines a set of geometric split directions/types (`cu.geoSplitDir`).
    *   **Motion Derivation (`EncCu::prepareGpmComboList`)**:
        *   For each geometric split direction, GPM selects two regular merge candidates (from `MergeCtx`) – one for each partition.
        *   `EncCu::prepareGpmComboList` evaluates combinations of split directions and pairs of merge candidates using SAD-based costs for each partition to create a list of promising GPM candidates (`GeoComboCostList`).
    *   **Prediction Blending (`InterPrediction::weightedGeoBlk`)**:
        *   `EncCu::generateMergePrediction` (when handling a GPM candidate) calls `InterPrediction::weightedGeoBlk`.
        *   This function generates predictions for the two partitions using their respective inherited merge candidate's motion.
        *   It then blends these two predictions according to the geometric split pattern. The VVC standard defines weighting masks (`g_globalGeoEncSADmask`, `g_weightOffset`) that specify how samples from each partition's prediction contribute to the final GPM prediction, especially along the boundary.
    *   **RDO and Signaling**: GPM candidates are evaluated in `EncCu::xCheckRDCostUnifiedMerge` via `addGpmCandsToPruningList`. The RD cost includes bits for the GPM flag, split direction, and the two chosen merge indices.

*   **Briefly Reiterate Other Advanced Inter Tools**:
    *   **CIIP (Combined Inter-Intra Prediction)**: Evaluated in `xCheckRDCostUnifiedMerge`. An inter prediction (from a merge candidate) is combined (averaged) with an intra prediction (typically Planar for luma, DM_CHROMA for chroma) for the same block. Useful for regions where parts are well-predicted by motion and other parts by intra.
    *   **DMVR (Decoder-side Motion Vector Refinement)**: A bi-prediction refinement technique. For a bi-predicted block, DMVR refines the MVs for sub-blocks by performing a local search at the decoder side (emulated at encoder). The encoder signals that DMVR should be used, and the decoder performs the refinement. MC is done by `InterPrediction::xProcessDMVR`.
    *   **BDOF (Bi-directional Optical Flow)**: Another bi-prediction refinement tool. It calculates an optical flow based correction that is added to the initial average of L0 and L1 predictions. The correction is derived from image gradients of the L0 and L1 predictions. MC by `InterPrediction::xApplyBDOF`.
    *   **SBT (Sub-Block Transform)**: While primarily a transform tool, its use is decided in `EncCu` and can be inter-dependent with inter mode decisions. If SBT is chosen for a CU's residual, it means the residual is split, and different transforms are applied to the sub-blocks. `InterSearch::encodeResAndCalcRdInterCU` tests SBT options.
    *   **IBC (Intra Block Copy)**: Already covered in MC. It's an inter-like mode that uses a block vector (BV) to copy a block from an already reconstructed area of the current picture. Tested in `EncCu::xCheckRDCostIBCMode` and `xCheckRDCostIBCModeMerge2Nx2N`.

These advanced tools allow VVenC to model a wider variety of motion and signal characteristics, leading to improved compression efficiency compared to relying solely on traditional translational motion models. The decision to use them is always driven by RD optimization within `EncCu`, guided by `EncModeCtrl`.


## 7. Overall Flow for an Inter CU

The process of encoding an inter-predicted Coding Unit (CU) in VVenC involves a coordinated effort primarily between `EncCu`, `InterSearch`, `InterPrediction`, and `EncModeCtrl`. The flow is driven by Rate-Distortion Optimization (RDO) to select the most efficient coding mode and its associated parameters.

1.  **Initiation by `EncCu` (`EncCu::xCompressCU`)**:
    *   The `EncCu` class begins compressing a CU. If inter prediction is to be evaluated (i.e., not an I-slice and intra prediction is not forced by other constraints), it proceeds to test various inter modes.
    *   A `CodingStructure` (`tempCS`) is set up to hold the data for the current mode being tested, and another (`bestCS`) stores the best mode found so far for this CU.
    *   The `EncModeCtrl` is initialized for the current CU (`m_modeCtrl.initCULevel`).

2.  **Mode Evaluation Loop (Controlled by `EncModeCtrl` and `EncCu`)**:
    `EncCu` iterates through a sequence of potential inter prediction modes. The `EncModeCtrl::tryMode` function is called before testing each major mode type to determine if it should be evaluated based on encoder settings and fast decision heuristics.

3.  **Testing AMVP-based Inter Modes (`EncCu::xCheckRDCostInter`, `EncCu::xCheckRDCostInterIMV`)**:
    *   **Motion Estimation (`InterSearch::predInterSearch` -> `InterSearch::xMotionEstimation`)**:
        *   For each reference picture in L0 and L1:
            *   AMVP candidates are derived (`CU::fillMvCand` via `xEstimateMvPredAMVP`).
            *   Integer pixel search (e.g., TZSearch) is performed, starting from the best AMVP candidate, to find an integer MV.
            *   Fractional pixel refinement (`xPatternSearchFracDIF`) is applied to get the final MV (e.g., quarter-pel precision).
            *   The best MV, reference index (`refIdx`), and MVP index (`mvpIdx`) are determined for uni-directional prediction for each list.
    *   **Bi-prediction Refinement**: If applicable, iterative refinement of L0 and L1 MVs for bi-prediction is performed, and SMVD might be tested.
    *   **Motion Compensation (`InterPrediction::motionCompensation`)**: The predicted block is generated using the determined MVs and reference pictures.
    *   **Residual Coding and RD Cost (`InterSearch::encodeResAndCalcRdInterCU`)**:
        *   The residual (Original - Prediction) is calculated.
        *   Transform, quantization (RDOQ), and entropy coding (estimation) are performed on the residual.
        *   The RD cost (`Distortion + λ * Rate_total`) is calculated.
    *   **Update Best (`EncCu::xCheckBestMode`)**: If this AMVP mode's RD cost is lower than `bestCS->cost`, `bestCS` is updated.

4.  **Testing Merge and Advanced Inter Modes (`EncCu::xCheckRDCostUnifiedMerge`)**:
    *   **Candidate Generation**:
        *   Regular merge candidates (spatial, temporal/HMVP, pairwise-averaged) are derived (`CU::getInterMergeCandidates`).
        *   MMVD candidates are generated by adding small MVDs to regular merge candidates (`CU::getInterMMVDMergeCandidates`).
        *   Affine merge candidates (including SbTMVP) are derived (`CU::getAffineMergeCand`).
        *   GPM candidates (combinations of two merge candidates and a split pattern) are prepared (`EncCu::prepareGpmComboList`).
        *   CIIP candidates are implicitly formed by combining each inter merge candidate with an intra prediction.
    *   **SATD-based Pruning**: A first pass evaluates these numerous candidates using a faster cost metric (SAD/SATD + rate for mode signaling) via functions like `addRegularCandsToPruningList`. The most promising candidates are stored in `m_mergeItemList`.
    *   **Full RDOQ for Pruned Candidates**:
        *   For each selected candidate from `m_mergeItemList`:
            *   The CU's motion information is set according to the candidate (e.g., `MergeItem::exportMergeInfo`).
            *   Motion Compensation (`EncCu::generateMergePrediction`, which calls `InterPrediction::motionCompensation` and potentially specialized functions like `InterPrediction::weightedGeoBlk` for GPM or `PelUnitBuf::weightCiip` for CIIP) generates the predicted block.
            *   Residual Coding and RD Cost (`InterSearch::encodeResAndCalcRdInterCU`) are performed as in AMVP.
            *   A "no residual" pass is also typically checked for each merge candidate to evaluate skip or merge-without-residual possibilities.
    *   **Update Best (`EncCu::xCheckBestMode`)**: If a merge-based mode yields a lower RD cost, `bestCS` is updated.

5.  **Testing IBC Modes (`EncCu::xCheckRDCostIBCMode`, `EncCu::xCheckRDCostIBCModeMerge2Nx2N`)**:
    *   If IBC is enabled:
        *   **IBC Merge**: Merge candidates are derived from spatial/temporal IBC neighbors (`CU::getIBCMergeCandidates`). These are evaluated with SATD and then full RDOQ.
        *   **IBC Search (`InterSearch::predIBCSearch`)**: A search for the best block vector (BV) within the current picture's reconstructed area is performed.
        *   Motion Compensation (`InterPrediction::motionCompensationIBC`) copies the block using the BV.
        *   Residual Coding and RD Cost are calculated.
    *   **Update Best (`EncCu::xCheckBestMode`)**: The best IBC mode is compared against `bestCS`.

6.  **Recursive CU Partitioning**:
    *   After evaluating all non-split modes for the current CU size/shape, `EncCu::xCompressCU` then evaluates potential splits (QT, BT, TT) if allowed by `EncModeCtrl::trySplit`.
    *   For each allowed split:
        *   `EncCu::xCheckModeSplit` is called.
        *   `EncCu::xCompressCU` is called recursively for each sub-CU resulting from the split.
        *   The sum of RD costs from the sub-CUs, plus the bits to signal the split type, forms the RD cost for this partitioning option.
    *   This split cost is compared with `bestCS->cost` (which holds the best cost for coding the current area *without* this specific split). If the split is better, `bestCS` is updated to reflect the split and the coding results of its children.

7.  **Final Decision and Storage**:
    *   After all non-split modes and all allowed split partitioning options have been evaluated for the current CU area, `bestCS` holds the CU/PU/TU structure and associated mode information (inter MVs, ref idx, merge idx, intra dir, etc.) that achieved the overall minimum RD cost.
    *   This optimal coding information from `bestCS` is then committed to the main `CodingStructure` of the picture (`cs.useSubStructure(*bestCS, ...)`).
    *   The CABAC contexts (`m_CABACEstimator->getCtx()`) are updated based on the chosen mode's contexts stored in `m_CurrCtx->best`.

This recursive process ensures that for each CTU, the encoder explores a tree of possible partitioning structures and, for each resulting CU, a wide range of intra and inter prediction modes, ultimately selecting the combination that provides the best rate-distortion trade-off. The `EncModeCtrl` plays a critical role in pruning this vast search space to keep the encoding complexity manageable.


## 8. Conclusion

VVenC's inter prediction framework is a highly sophisticated and integral part of its compression capabilities, designed to effectively exploit temporal redundancies in video sequences. It encompasses a wide array of tools and techniques, from foundational block matching with translational motion vectors to advanced models like affine and geometric partitioning, alongside specialized modes such as Intra Block Copy and Combined Inter-Intra Prediction.

The core of the inter prediction process involves a meticulous, Rate-Distortion Optimized (RDO) search. Motion Estimation, primarily handled by the `InterSearch` class, employs efficient algorithms like TZSearch and hierarchical fractional-pel refinement to find accurate motion vectors. Motion Compensation, executed by `InterPrediction`, then uses these vectors to generate predicted blocks, utilizing VVC's precise interpolation filters.

The decision-making, orchestrated by `EncCu` and guided by `EncModeCtrl`, evaluates a comprehensive set of inter prediction modes. This includes standard AMVP-based prediction, an extensive list of merge candidates (further enhanced by MMVD and SbTMVP), and more complex tools like affine motion models and Geometric Partitioning Mode. Each candidate mode is rigorously tested, its RD cost is calculated, and the mode that offers the best trade-off between coding bits and distortion is selected. Advanced techniques like DMVR and BDOF further refine bi-prediction quality.

The system's strength lies in its hierarchical approach, where fast pre-selection methods (e.g., SATD-based pruning of merge candidates) are used to narrow down the search space before computationally intensive full RDOQ is performed on the most promising options. This, combined with the rich set of coding tools, allows VVenC to adapt effectively to diverse video content and achieve high compression efficiency, as mandated by the VVC standard. Understanding this intricate interplay of ME, MC, and RDO mode decision is key to appreciating the encoder's performance.
