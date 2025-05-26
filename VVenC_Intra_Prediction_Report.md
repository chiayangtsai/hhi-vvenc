# VVenC Intra Prediction: A Comprehensive Explanation

## 1. Introduction

Intra-frame prediction (intra prediction) is a fundamental technique in video coding that aims to reduce spatial redundancy within a single frame or picture. Instead of transmitting the raw pixel values of a block, intra prediction uses already coded and reconstructed neighboring samples within the same picture to predict the current block. Only the prediction mode and the residual (the difference between the original block and the predicted block) are then encoded and transmitted, leading to significant compression gains.

The VVenC encoder, being an implementation of the H.266/VVC standard, incorporates a sophisticated and extensive set of intra prediction tools designed to maximize coding efficiency for intra-coded blocks. This report details the mechanisms, algorithms, and data structures involved in VVenC's intra prediction process.

## 2. Key Classes and Data Structures

Several classes and data structures are central to the intra prediction process in VVenC:

*   **Main Classes**:
    *   **`IntraSearch`**: Responsible for the intra mode decision process. It evaluates various intra prediction modes for a given Coding Unit (CU) and selects the one that minimizes the rate-distortion (RD) cost.
    *   **`IntraPrediction`**: Performs the actual generation of the prediction signal based on a chosen intra mode and neighboring reconstructed samples.
    *   **`MatrixIntraPrediction`**: A specialized class used by `IntraPrediction` to handle Matrix-based Intra Prediction (MIP).
    *   **`EncCu`**: Manages the encoding process for a single Coding Unit, including deciding whether to use intra or inter prediction and invoking `IntraSearch` if intra is chosen.
    *   **`CodingUnit`**: Stores the final encoding decisions for a CU, including the selected intra prediction mode and related parameters.
    *   **`CodingStructure`**: Holds CUs, Prediction Units (PUs), and Transform Units (TUs) for a region of the picture, providing context and access to neighboring data.

*   **Key Data Structures**:
    *   **`CodingUnit` Fields for Intra**:
        *   `predMode`: Set to `MODE_INTRA`.
        *   `intraDir[MAX_NUM_CH]`: Stores the selected luma and chroma intra prediction mode indices (e.g., `PLANAR_IDX`, `DC_IDX`, angular modes 2-66 for luma; `DM_CHROMA_IDX`, `LM_CHROMA_IDX` for chroma).
        *   `mipFlag`, `mipTransposedFlag`: Indicate use and type of MIP.
        *   `ispMode`: Specifies if Intra Subpartitions (ISP) are used and the split direction.
        *   `multiRefIdx`: Index for Multiple Reference Line (MRL) intra prediction.
        *   `bdpcmM[MAX_NUM_CH]`: Mode for Block Differential Pulse Code Modulation (BDPCM).
    *   **`IntraSearch::ModeInfo`**: An internal temporary structure in `IntraSearch` holding parameters (mode ID, MIP flags, MRL index, ISP mode) of a candidate intra mode during evaluation.
    *   **`IntraPrediction::m_refBuffer`**: Internal buffers in `IntraPrediction` to store unfiltered and filtered reference samples fetched from reconstructed neighbors.
    *   **`IntraPredParam` (m_ipaParam in `IntraPrediction`)**: A structure holding parameters for a specific intra prediction operation (e.g., prediction angle, flags for reference filtering, PDPC).
    *   **MIP Data Structures (in `MatrixIntraPrediction`)**: Includes `m_reducedBoundary` for downsampled boundary reference samples. The MIP prediction matrices are typically implicit in the code.
    *   **MPM List**: A temporary array, typically derived by `CU::getIntraMPMs`, holding the Most Probable Modes for efficient signaling.

## 3. Intra Mode Decision (`IntraSearch`)

The primary goal of the `IntraSearch` class is to find the intra prediction mode for a luma or chroma CU that minimizes a rate-distortion (RD) cost, balancing coding bits with prediction accuracy. This is mainly orchestrated by `IntraSearch::estIntraPredLumaQT` for luma and `IntraSearch::estIntraPredChromaQT` for chroma.

*   **Candidate Mode Generation (`xEstimateLumaRdModeList`)**:
    A list of candidate modes is generated for full RD evaluation through a multi-step process:
    1.  **Most Probable Modes (MPM)**: `CU::getIntraMPMs()` derives a list of MPMs based on the intra modes of neighboring (already coded) blocks. These are often highly probable and are prioritized.
    2.  **DC, Planar, and Angular Modes**: DC and Planar modes are typically always considered. A subset of the 65 angular modes (modes 2-66) is also added.
    3.  **Matrix-based Intra Prediction (MIP)**: If enabled and applicable for the CU size, MIP modes (both transposed and non-transposed) are included as candidates.
    4.  **Fast Search Strategies (SATD-based Pre-selection)**:
        *   To avoid the high computational cost of full RDOQ for all possible modes, a pre-selection step is performed using a faster cost metric: Sum of Absolute Transformed Differences (SATD), often referred to as Hadamard cost.
        *   For each potential mode (angular, DC, Planar, MRL, MIP), a prediction is generated, the SATD cost is calculated against the original block, and an estimate of the mode signaling bits is added.
        *   Modes are sorted based on this SATD cost, and only a limited number of top candidates (`numModesForFullRD`) are passed to the full RDOQ stage.
        *   Heuristics like `m_pcEncCfg->m_usePbIntraFast` (for inter CUs considering intra) and `m_pcEncCfg->m_FastIntraTools` further refine this list, potentially reducing the number of candidates or disabling certain tools (LFNST, MTS, ISP) based on early cost evaluations or CU properties.

*   **Evaluation of Each Candidate (`xIntraCodingLumaQT`, `xIntraCodingTUBlock`)**:
    Each mode from the refined candidate list undergoes a full RDOQ process:
    1.  **Prediction Signal Generation**: The `IntraPrediction` class is invoked to generate the prediction samples for the current candidate mode (details in Section 4).
    2.  **Residual Calculation**: The prediction is subtracted from the original CU samples to obtain the residual signal.
    3.  **Transform and Quantization**: The `TrQuant` class is used to apply a forward transform (DCT-II, DST-VII, or MTS transforms if enabled) to the residual and then quantize the transform coefficients. This step itself is rate-distortion optimized (RDOQ) to select optimal quantization levels.
    4.  **Rate Estimation**: The `CABACWriter` (in estimation mode) is used to estimate the number of bits required to:
        *   Signal the chosen intra prediction mode (considering MPMs for efficiency).
        *   Signal other syntax elements like LFNST index, MTS index, ISP mode.
        *   Encode the quantized transform coefficients (CBFs, significance maps, coefficient signs and levels).
    5.  **Distortion Calculation**: The reconstructed CU is formed by adding the de-quantized, inverse-transformed residual to the prediction. Distortion (typically Sum of Squared Errors - SSE) between the original and reconstructed CU is calculated.
    6.  **RDO Cost Calculation**: The total RDO cost for the mode is calculated as `Cost = Distortion + λ * Rate`, where `λ` is a Lagrange multiplier dependent on the CU's quantization parameter (QP).

*   **Selection of the Best Mode**:
    The RDO costs of all evaluated candidate modes are compared. The mode that yields the minimum RDO cost is selected as the best intra prediction mode for the CU. Its parameters (direction, MIP flags, ISP mode, etc.) are stored in the `CodingUnit` structure.

## 4. Prediction Signal Generation (`IntraPrediction`)

The `IntraPrediction` class is responsible for generating the actual predictive pixel values based on a given intra mode and the reconstructed samples from neighboring blocks.

*   **Reference Sample Preparation**:
    *   `initIntraPatternChType()`: This function prepares the reference samples.
    *   `xFillReferenceSamples()`: Fetches reconstructed samples from neighboring blocks (above, left, top-left, top-right, bottom-left of the current CU). If neighbors are unavailable (e.g., at slice boundaries), padding is applied by replicating the closest available sample. These samples are stored in `m_refBuffer[compID][PRED_BUF_UNFILTERED]`.
    *   `xFilterReferenceSamples()`: If required by the mode or block size (controlled by `m_ipaParam.refFilterFlag`), a 3-tap `[1 2 1]/4` smoothing filter is applied to the unfiltered reference samples. The result is stored in `m_refBuffer[compID][PRED_BUF_FILTERED]`. The `getPredictorPtr()` method then provides access to either filtered or unfiltered samples.

*   **DC Prediction (`xPredIntraDc`)**:
    *   Calculates the average of the available top and left reference samples.
    *   Fills the entire prediction block with this average DC value.

*   **Planar Prediction (`xPredIntraPlanar`)**:
    *   Generates a smooth gradient across the block.
    *   Uses the top-left, top-row, and left-column reference samples to perform a bilinear-like interpolation for each pixel in the prediction block, effectively creating smooth transitions from the boundaries.

*   **Angular Prediction (`xPredIntraAng`)**:
    *   Handles the 65 directional modes (modes 2-66).
    *   **Projection**: For each pixel in the prediction block, a line is projected along the specified intra prediction angle until it intersects the boundary of available reference samples.
    *   **Interpolation/Smoothing**:
        *   If the projection falls directly on an integer reference sample position, that sample is copied.
        *   If the projection falls between reference samples (fractional-pel position), interpolation is performed. Luma prediction may use a 4-tap cubic-like filter or a simpler smoothing filter depending on the angle and configuration (`m_ipaParam.interpolationFlag`). Chroma prediction typically uses linear interpolation.

*   **Wide-Angle Intra Prediction (WAIP)**:
    *   WAIP is not a distinct set of modes but rather how standard angular modes are adapted for non-square blocks.
    *   `IntraPrediction::getWideAngle()` adjusts the interpretation of the angular mode index based on the block's aspect ratio, effectively selecting "wider" projection angles.
    *   The reference sample fetching (`m_topRefLength`, `m_leftRefLength` are `2*width`, `2*height`) and extension mechanisms in `xPredIntraAng` (replicating the last sample or projecting from the side reference for negative angles) ensure that valid reference data is available even for these wide projections.

*   **Position Dependent Prediction Combination (PDPC)**:
    *   PDPC refines the initial prediction (Planar, DC, or angular) by adding a correction term.
    *   The correction is stronger near the reference sample boundaries and decays towards the interior of the block. It's calculated using the initial predicted sample at the current position and the closest actual boundary reference samples.
    *   Functions like `IntraPredSampleFilter_Core`, `IntraHorVerPDPC_Core`, and `IntraAnglePDPC_Core` implement PDPC for different mode types.

*   **Matrix-based Intra Prediction (MIP) (`MatrixIntraPrediction` class)**:
    *   MIP offers an alternative to angular prediction, particularly for textured regions.
    *   `MatrixIntraPrediction::prepareInputForPred()`: The top and left boundary reference samples are downsampled.
    *   `MatrixIntraPrediction::predBlock()`: The prediction is generated by multiplying these downsampled boundary samples with pre-defined matrices (weights) and then upsampling the result. Different matrices are used for different MIP modes. Transposition of the block or matrices can also be applied.

*   **Cross-Component Linear Model (CCLM) (`predIntraChromaLM`, `xGetLMParameters`)**:
    *   Used for predicting chroma components from the reconstructed luma signal.
    *   **Luma Sample Preparation (`loadLMLumaRecPels`)**: Reconstructed luma samples corresponding to the chroma block's location and its neighbors are fetched and downsampled to match chroma resolution.
    *   **Linear Model Derivation (`xGetLMParameters`)**: A linear model `Chroma = a * Luma + b` is derived. The parameters `a` (slope) and `b` (offset) are estimated using pairs of (downsampled luma, reconstructed chroma) samples from available top and/or left neighbors.
    *   **Prediction**: The derived linear model is applied to the downsampled reconstructed luma samples of the current block to generate the chroma prediction.

## 5. Intra Subpartitions (ISP)

Intra Subpartitions (ISP) is a VVC tool that allows an intra-coded CU to be further divided into smaller horizontal or vertical sub-blocks. Each sub-block is then predicted and reconstructed sequentially, allowing later sub-blocks to use previously reconstructed sub-blocks within the same CU as reference.

*   **Handling in `IntraSearch`**:
    *   `IntraSearch::estIntraPredLumaQT` checks if ISP is allowed (`sps.ISP && CU::canUseISP(...)`).
    *   If ISP is tested, the main loop iterates through ISP modes (horizontal splits, vertical splits, or no ISP).
    *   `IntraSearch::xTestISP` is a key function that evaluates the RD cost of an ISP mode. It iterates through the subpartitions, performing intra prediction and RDOQ for each one, accumulating costs and bits.
    *   The decision to use ISP and the specific split direction is made based on the overall RD cost compared to non-ISP modes and other ISP split options.

## 6. Overall Flow for an Intra CU

The process for encoding an intra CU generally follows this sequence:

1.  **Decision to Test Intra**: `EncCu` (or a similar CU encoding management class) determines that intra prediction should be evaluated for the current CU. This might be because it's an I-slice, or intra is being tested against inter modes in P/B-slices.
2.  **Invoke `IntraSearch`**: `EncCu` calls a main method in `IntraSearch` (e.g., `EncCu::encodeCtu`, which leads to intra search path if intra is decided).
3.  **Mode Search (`IntraSearch::estIntraPredLumaQT` / `estIntraPredChromaQT`)**:
    *   `IntraSearch` generates a list of candidate intra modes (angular, DC, Planar, MIP, etc.) using fast pre-selection methods (SATD).
    *   For each promising candidate mode:
        *   It calls methods in `IntraPrediction` (e.g., `predIntraAng`, `predIntraPlanar`) to generate the actual prediction signal using prepared reference samples.
        *   It calculates the residual (Original - Prediction).
        *   It calls methods in `TrQuant` to transform and quantize the residual.
        *   It estimates the bits needed to signal the mode and the quantized residual.
        *   It calculates the RDO cost (`Distortion + λ * Rate`).
    *   ISP modes are tested as part of this loop, involving recursive prediction and coding of subpartitions.
4.  **Best Mode Selection**: `IntraSearch` selects the intra mode (including LFNST, MTS, ISP choices) that yielded the lowest RDO cost.
5.  **Store Results**: The chosen intra prediction mode and related parameters (e.g., `intraDir`, `mipFlag`, `ispMode`) are stored in the `CodingUnit` data structure. The quantized coefficients are also stored in associated `TransformUnit` structures.
6.  **Bitstream Generation**: Later, during entropy coding, the information stored in the `CodingUnit` (and `TransformUnit`) is used to write the appropriate syntax elements to the bitstream.

## 7. Conclusion

VVenC's intra prediction framework is a complex interplay of mode selection strategies, sophisticated prediction signal generation techniques, and specialized tools like MIP, ISP, and CCLM. By meticulously evaluating a wide range of options and employing rate-distortion optimization at multiple levels, VVenC strives to achieve high compression efficiency for intra-coded regions of a video sequence. The modular design, with distinct classes for searching (`IntraSearch`) and prediction generation (`IntraPrediction`), allows for both sophisticated algorithms and manageable code structure.
