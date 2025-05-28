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
