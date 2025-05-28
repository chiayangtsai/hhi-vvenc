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

These classes and structures collectively provide the framework for VVenC to perform complex motion estimation, generate predictions, and make efficient inter mode decisions.Okay, I will continue generating the sections for the "VVenC Inter Prediction Analysis Report".

**Step 3: Generate Section 3 - Motion Estimation (ME) (`InterSearch`)**
