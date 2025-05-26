# VVenC Encoder: Program Flow Analysis Report

## 1. Introduction

This document describes the overall program flow of the Fraunhofer VVenC (Versatile Video Encoder), an H.266/VVC (Versatile Video Coding) software implementation. It aims to provide software engineers with a clear understanding of the encoder's architecture, from the application layer down to the core encoding processes, highlighting how different components interact.

## 2. Application Layer

The VVenC project provides two main command-line applications for encoding: `vvencapp` and `vvencFFapp`.

*   **Purpose**:
    *   **`vvencapp`**: This application serves as a reference encoder that directly consumes raw YUV (YCbCr) video data from input files. It's suitable for scenarios where the input is already in the uncompressed YUV format.
    *   **`vvencFFapp`**: This application extends `vvencapp` by integrating FFmpeg for input processing. It can read and decode a wide variety of common video container formats (e.g., MP4, MOV, AVI) and compressed video formats, convert the decoded frames to YUV, and then pass them to the VVenC encoding library. This offers greater flexibility for users with standard video files.

*   **Configuration and C API Interaction**:
    *   Both applications use a common utility (`apputils::program_options` or `apputils::VVEncAppCfg`) to parse command-line arguments and read settings from configuration files.
    *   They interact with the VVenC encoder core via its public C API (defined in `vvenc.h`).
    *   The general workflow involves:
        1.  Creating an encoder instance: `vvenc_encoder_create()`.
        2.  Initializing a `vvenc_config` struct with default values (`vvenc_init_default()`) and then overriding these with parsed user settings (resolution, QP, rate control parameters, GOP structure, etc.). Presets can be applied using `vvenc_init_preset()`. Additional parameters can be set using `vvenc_set_param()`.
        3.  Opening the encoder with the configuration: `vvenc_encoder_open(encoder_handle, &config)`.
        4.  Optionally, retrieving the actual configuration used by the encoder: `vvenc_get_config(encoder_handle, &actual_config)`.

*   **Input Reading and Encoding Loop**:
    *   **`vvencapp`**: Reads YUV frames directly from a file using `apputils::YuvFileIO`.
    *   **`vvencFFapp`**: Uses FFmpeg libraries (`libavformat`, `libavcodec`, `libswscale`) to open, demux, decode, and convert input video frames to the YUV format required by the VVenC library.
    *   **Encoding Loop (Common Logic)**:
        1.  A loop reads input frames until no more are available or a specified frame count is reached.
        2.  Each YUV frame is packaged into a `vvencYUVBuffer` structure. Timestamps (`cts`) and sequence numbers are typically set.
        3.  The core encoding call is `vvenc_encode(encoder_handle, yuv_buffer, access_unit_output, &encode_done_flag)`.
            *   If `yuv_buffer` is `nullptr`, it signals to the encoder that it should flush any buffered frames (end-of-sequence).
        4.  The `vvencAccessUnit` structure is populated by the encoder with the NAL (Network Abstraction Layer) units of the encoded frame.
        5.  The application writes the payload of the `vvencAccessUnit` (which contains the VVC bitstream for one access unit) to an output file.
        6.  The loop continues until `encode_done_flag` is set to true by `vvenc_encode`, indicating all frames (including flushing) have been processed.
    *   **Multi-pass Encoding**: Both applications support multi-pass rate control. This involves iterating the encoding loop multiple times. In the first pass(es), statistics are gathered (and potentially saved to a file via `vvencappCfg.m_RCStatsFileName`). In the final pass, these statistics are used by the encoder (initialized via `vvenc_init_pass()`) to improve rate control accuracy.
    *   Once encoding is complete, `vvenc_encoder_close(encoder_handle)` is called to release resources.

## 3. C API to C++ Bridge

The VVenC library is implemented in C++, but it exposes a C API for broader interoperability and ABI stability. This bridge is primarily facilitated by `source/Lib/vvenc/vvenc.cpp` and the C++ class `vvenc::VVEncImpl`.

*   **Role of `vvenc.cpp` and `vvenc::VVEncImpl`**:
    *   **`vvenc.cpp`**: Implements the C functions declared in `vvenc.h`. These functions act as thin wrappers.
    *   **`vvenc::VVEncImpl`**: This C++ class (defined in `source/Lib/vvenc/vvencimpl.h` and implemented in `source/Lib/vvenc/vvencimpl.cpp`) is the main entry point and facade for the C++ encoder core. It encapsulates the primary encoding logic and manages the internal state and components of the encoder.
    *   **Opaque Pointer**: The C API uses an opaque pointer (`vvencEncoder*`) to represent an encoder instance. Internally, this pointer is a `vvenc::VVEncImpl*`.

*   **Mapping of C API Calls to `VVEncImpl` Methods**:
    *   `vvenc_encoder_create()`: Creates an instance of `VVEncImpl` (`new vvenc::VVEncImpl()`) and returns it cast to `vvencEncoder*`.
    *   `vvenc_encoder_open(enc, config)`: Casts `enc` to `VVEncImpl*` and calls its `init(config)` method.
    *   `vvenc_encode(enc, yuv_buffer, access_unit, encode_done)`: Casts `enc` to `VVEncImpl*` and calls its `encode(yuv_buffer, access_unit, encode_done)` method.
    *   `vvenc_encoder_close(enc)`: Casts `enc` to `VVEncImpl*`, calls its `uninit()` method, and then `delete`s the instance.
    *   `vvenc_get_config(enc, config)`: Calls `VVEncImpl::getConfig(config)`.
    *   `vvenc_init_pass(enc, pass, stats_filename)`: Calls `VVEncImpl::initPass(pass, stats_filename)`.
    *   Other C API functions for parameter setting, information retrieval, etc., similarly map to corresponding methods in `VVEncImpl`.

## 4. Core Encoder Library (`EncLib`)

The `vvenc::VVEncImpl` class delegates the main encoding work to `vvenc::EncLib` (defined in `source/Lib/EncoderLib/EncLib.h` and `source/Lib/EncoderLib/EncLib.cpp`). `EncLib` manages a pipelined architecture for video processing.

*   **Pipeline Architecture (`EncStage`)**:
    *   `EncLib` breaks down the encoding process into a series of stages, where each stage is an instance of a class derived from `vvenc::EncStage`.
    *   These stages are stored in `EncLib::m_encStages` and linked sequentially (`EncStage::linkNextStage()`).
    *   Data flows from one stage to the next, typically encapsulated within `PicShared` objects.

*   **Key Stages**:
    1.  **`PreProcess` (`m_preProcess`)**:
        *   The first stage. Receives YUV data from `VVEncImpl` (which got it from the C API).
        *   Copies input YUV to internal `PicShared` buffers.
        *   Handles initial GOP structure decisions and picture numbering.
    2.  **`MCTF` (`m_MCTF`)** (Motion Compensated Temporal Filter - Optional):
        *   If enabled, performs temporal filtering on input frames to reduce noise and improve compressibility. Operates on a window of frames.
    3.  **`EncGOP` (as Pre-Analyzer/Lookahead) (`m_preEncoder` - Optional)**:
        *   If lookahead is enabled, this instance of `EncGOP` performs a fast, lightweight pre-encoding pass.
        *   Gathers statistics (complexity, motion) for the `RateCtrl` module.
        *   Uses a simplified encoder configuration for speed. Output bitstream is discarded.
    4.  **`EncGOP` (as Main GOP Encoder) (`m_gopEncoder`)**:
        *   The core encoding stage. Takes pictures (from `MCTF` or `PreProcess`) and generates the VVC bitstream for a Group of Pictures (GOP).
        *   Performs prediction, transform, quantization, entropy coding, and loop filtering.
        *   Interacts closely with `RateCtrl`.

*   **Role of `PicShared` for Data Transfer**:
    *   `vvenc::PicShared` objects are central data carriers that move through the `EncLib` pipeline.
    *   They encapsulate YUV picture data (original, filtered, reconstructed) and associated metadata (POC, timestamps, frame type, QP information, processing flags).
    *   `EncLib` manages a list of `PicShared` objects (`m_picSharedList`) to reuse buffers and minimize allocations.

*   **Parallelism with `NoMallocThreadPool`**:
    *   `EncLib` can utilize a `vvenc::NoMallocThreadPool` if `m_encCfg.m_numThreads > 0`.
    *   This thread pool is passed to stages like `MCTF` and `EncGOP`, which can then parallelize tasks such as encoding multiple CTUs (Coding Tree Units) simultaneously or processing different parts of algorithms in parallel.

## 5. GOP Encoding Process (`EncGOP`)

The `vvenc::EncGOP` class is responsible for the encoding of an entire Group of Pictures.

*   **Management of GOP Encoding**:
    *   **Initialization**: Sets up Parameter Sets (VPS, SPS, PPS), RPL (Reference Picture List) logic, and creates a pool of `EncPicture` objects (each `EncPicture` handles one picture).
    *   **Picture Initialization & Ordering**: Receives `PicShared` objects. Initializes slice headers for each picture (`xInitFirstSlice`), determining slice type, NAL unit type, reference lists, etc., based on the GOP structure (`GOPEntry`). Manages APS for ALF/LMCS.
    *   **Picture Processing**: For each picture, it obtains a free `EncPicture` instance and calls `EncPicture::compressPicture()` to perform the actual encoding. Multi-threading can be employed here for frame-level parallelism (multiple `EncPicture` instances working concurrently) or slice/CTU-level parallelism within `EncPicture::compressPicture()`.
    *   **Output Generation**: Assembles NAL units (parameter sets, slice data, SEIs) from encoded pictures into `AccessUnitList` objects, which are then passed up to `EncLib` and `VVEncImpl`.

*   **Interaction with Rate Control (`RateCtrl`)**:
    *   `EncGOP` works closely with the `RateCtrl` module.
    *   Before encoding a picture, `RateCtrl::initRateControlPic()` is called to set its QP and lambda.
    *   After encoding, `RateCtrl::updateAfterPicEncRC()` updates the RC model with actual bits used.
    *   If `EncGOP` is in pre-analysis mode, it feeds statistics to `RateCtrl` via `RateCtrl::addRCPassStats()`.

*   **Delegation to Slice and CU-Level Processing**:
    *   `EncGOP` delegates the encoding of an individual picture to an `EncPicture` object.
    *   `EncPicture` further delegates the encoding of a slice to `EncSlice` (not explicitly detailed in this report but is the next logical step).
    *   `EncSlice` then manages the encoding of CTUs within that slice, typically by an `EncCu` class. `EncCu` handles mode decisions (intra/inter prediction, partitioning) and invokes lower-level modules for transform, quantization, and entropy coding of residuals.

## 6. Overall Data Flow Summary

The journey of a picture through the VVenC encoder can be summarized as:

1.  **Input (Application Layer)**:
    *   `vvencapp`: Raw YUV data is read from a file.
    *   `vvencFFapp`: A video file is read by FFmpeg, decoded, and converted to YUV.
    *   The YUV data is placed into a `vvencYUVBuffer`.

2.  **C API Call**:
    *   The application calls `vvenc_encode()` with the `vvencYUVBuffer`.

3.  **C API to C++ Bridge (`VVEncImpl`)**:
    *   `vvenc_encode()` (in `vvenc.cpp`) casts the `vvencEncoder*` to `VVEncImpl*` and calls `VVEncImpl::encode()`.

4.  **Core Encoder Library (`EncLib`)**:
    *   `VVEncImpl::encode()` passes the `vvencYUVBuffer` to `EncLib::encodePicture()`.
    *   `EncLib` obtains a free `PicShared` object and copies the YUV data into it.
    *   The `PicShared` object enters the pipeline:
        *   **`PreProcess`**: Initial processing and setup.
        *   **`MCTF`** (Optional): Temporal filtering. The `PicShared` object now contains the filtered YUV.
        *   **`EncGOP` (Pre-Analysis)** (Optional): If lookahead is enabled, a lightweight encoding pass occurs. Statistics are sent to `RateCtrl`. The `PicShared` object is typically reused or its bitstream discarded. (For the main path, assume a new `PicShared` or the one from MCTF proceeds).
        *   **`EncGOP` (Main Encoding)**: This stage takes the `PicShared` object (containing original or filtered YUV).
            *   It orchestrates the encoding of the picture via an `EncPicture` instance.
            *   `EncPicture` (with `EncSlice` and `EncCu`) performs prediction, transform, quantization, and entropy coding.
            *   Reconstructed samples are stored back in the `PicShared` object (for future reference frames).
            *   Encoded slice data (bitstreams) are generated.

5.  **Output Assembly**:
    *   `EncGOP` assembles NAL units (parameter sets, slice data from `EncPicture`, SEIs) into an `AccessUnitList`.
    *   This `AccessUnitList` is passed up to `EncLib`.
    *   `EncLib` passes it to `VVEncImpl`.
    *   `VVEncImpl` populates the `vvencAccessUnit` provided by the C API caller.

6.  **Return to Application**:
    *   `vvenc_encode()` returns. The application now has the encoded bitstream for one access unit in `vvencAccessUnit.payload`.
    *   The application writes this payload to the output file.

This cycle repeats for all input pictures. Flushing is handled by calling `vvenc_encode()` with a `nullptr` YUV buffer, which propagates a flush signal down the pipeline.

## 7. Conclusion

The VVenC encoder exhibits a modular and pipelined architecture. It clearly separates concerns: the application layer for user interaction and I/O, a C API for interoperability, a C++ bridge (`VVEncImpl`) to the core, and a core library (`EncLib`) that uses a staged approach for processing. Within the core, `EncGOP` manages GOP-level encoding, delegating picture and block-level details to specialized classes. This design facilitates maintainability, allows for different components to be developed and optimized somewhat independently, and enables efficient parallel processing through its thread pool and pipeline structure.
