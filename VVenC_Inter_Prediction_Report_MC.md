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

This detailed process ensures that for any given inter mode and its associated motion parameters, an accurate prediction block is generated, forming the basis for residual calculation and subsequent encoding steps.Okay, I will continue generating the sections for the "VVenC Inter Prediction Analysis Report".

**Step 5: Generate Section 5 - Inter Mode Decision (`EncCu` with `InterSearch` and `EncModeCtrl`)**
