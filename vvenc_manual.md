# VVenc Manual

This guide explains how to use the VVenc command-line encoder (`vvencapp` or `vvenc`) to generate I-frame only H.266/VVC bitstreams, focusing on common rate control methods. It provides an overview of typical parameters and offers example command lines. However, always refer to the encoder's built-in help or official documentation for the most accurate and up-to-date information.

## Finding Built-in Help

VVenc comes with a built-in help system that provides a quick way to see all available commands and options. This is often the first place to look if you're unsure about how to use a particular feature or what options are available.

To access the built-in help, open your command line terminal and type one of the following commands (the executable might be `vvencapp` or `vvenc` depending on your installation; examples will use `vvencapp`):

```bash
vvencapp --help 
```

or

```bash
vvencapp -h
```

Executing either of these commands will display a list of all available parameters and their descriptions directly in your terminal. This output will typically include:

*   **General usage information:** How to structure your `vvencapp` commands.
*   **A list of options:** These are flags you can use to control the encoding process (e.g., setting the quality, input/output files, specific encoding features). Each option will usually have a short and a long form (e.g., `-h` and `--help`).
*   **Brief explanations:** A short description for each option, explaining what it does.

This built-in help is an invaluable resource for quickly referencing command-line parameters.

## Forcing I-Frame Only Encoding

To force VVenc to encode every frame as an I-frame (Intra-coded frame), effectively creating an I-frame only stream, you typically need to configure the encoder to have an Intra period of 1. This means that each Group of Pictures (GOP) will consist of only a single I-frame.

The most common way to achieve this is by setting the Intra period or GOP size parameter to 1. Look for parameters in the output of `vvencapp --help` such as:

*   `--IntraPeriod=1`
*   `--GOPSize=1`

Some encoders might also offer a specific flag to force I-frames, though this is less common for settings like GOP size. For example, you might look for an option like `--ForceIntra`, but relying on the Intra period or GOP size is the standard approach.

Setting the Intra period to 1 ensures that no P-frames (Predicted) or B-frames (Bi-predictive) are used, resulting in each frame being independently decodable. This can be useful for specific applications like video editing, archiving, or scenarios where random access to any frame is critical, though it will significantly increase the output file size compared to using inter-frame prediction.

## Rate Control Methods

VVenc, like other video encoders, offers several rate control methods to manage the trade-off between video quality and file size (bitrate). Understanding these methods will help you choose the best one for your needs.

### Constant QP (Quantization Parameter)

*   **Effect:** This mode aims for constant video quality. The Quantization Parameter (QP) is a value (typically from 0 to 63 for VVC) that controls the level of compression for each coding unit. A lower QP means less compression (higher quality, larger file size), while a higher QP means more compression (lower quality, smaller file size). In Constant QP mode, the same QP is applied to all parts of the video. This results in a variable bitrate, as complex scenes will require more bits to maintain the target QP, while simpler scenes will require fewer bits.
*   **Typical Parameters:** Look for options like:
    *   `--QP <value>` (e.g., `--QP 28`)
    *   `--ConstQP <value>`
    *   `--InitialQP <value>` (often used when rate control is explicitly disabled, e.g., with an option like `--RateControl=0` or a similar value indicating QP-based control)
*   **Use Case:** Useful when consistent quality across the entire video is the primary goal, and file size is a secondary concern or can vary.

### Constant Bitrate (CBR)

*   **Effect:** This mode attempts to maintain a specific target average bitrate over a defined window or the entire duration of the video. The encoder will adjust the QP up or down as needed to meet this target. This means that quality may fluctuate, with complex scenes potentially showing lower quality (as the encoder has to compress more aggressively to stay within the bitrate) and simpler scenes potentially showing higher quality.
*   **Typical Parameters:** Look for options like:
    *   `--Bitrate <kbps>` (e.g., `--Bitrate 5000` for 5 Mbps)
    *   `--TargetBitrate <kbps>`
    *   This mode often needs to be explicitly enabled via a parameter like `--RateControl=1` or `--RateControlMode=CBR` (the exact names can vary).
*   **Use Case:** Often used for streaming scenarios where bandwidth is limited and a predictable data rate is crucial.

### Variable Bitrate (VBR)

*   **Effect:** This mode also aims for a target average bitrate but generally offers more flexibility than CBR to allocate more bits to complex scenes and fewer to simpler scenes, resulting in more consistent quality for a given file size compared to CBR. It's often a good balance between quality and file size.
*   **Typical Parameters:**
    *   `--Bitrate <kbps>` (e.g., `--Bitrate 5000`)
    *   `--TargetBitrate <kbps>`
    *   Similar to CBR, this mode usually needs to be explicitly enabled via a parameter like `--RateControl=2` or `--RateControlMode=VBR`. Some encoders might also have settings for a maximum bitrate in VBR mode.
*   **Use Case:** A common choice for general-purpose encoding where good quality relative to file size is desired, and strict adherence to a constant bitrate isn't necessary.

### Other Rate Control Modes

Modern encoders may offer additional rate control modes. One popular mode found in other encoders (like x264, x265) is **Constant Rate Factor (CRF)**. CRF aims for a constant perceptual quality level, similar to Constant QP, but often does a better job by considering how humans perceive quality. Check if VVenc supports a similar mode via `vvencapp --help`.

**Always Check the Help Output**

The exact parameter names, available rate control modes, and their specific numerical identifiers (e.g., for `--RateControl`) can vary between different versions of VVenc or even different builds.

Therefore, it is crucial to consult the built-in help for the most accurate and up-to-date information:

```bash
vvencapp --help
```

This will provide the definitive list of rate control options supported by your specific VVenc version.

## Example Command Lines

Below are some example command lines to illustrate how to combine I-frame only encoding with different rate control methods. Remember to replace placeholders like `input.yuv`, `<width>`, `<height>`, `<framerate>`, `<qp_value>`, and `<bitrate_kbps>` with your actual values.

**Common Parameters Used in Examples:**

*   `-i input.yuv`: Specifies the input raw video file (e.g., YUV 4:2:0 planar).
*   `-o output.vvc`: Specifies the output encoded file name.
*   `--Size <width>x<height>`: Sets the video resolution (e.g., `1920x1080`). Alternative parameters might be `-s` or separate `-w` and `-h`.
*   `--Rate <framerate>`: Sets the input frame rate (e.g., `25`, `30000/1001`). Alternative parameters might be `--Framerate` or `-f`.
*   `--IntraPeriod=1`: Forces I-frame only encoding.

**Important:** The exact parameter names and values (especially for `--RateControl`) are illustrative and based on common encoder patterns. **Always verify with `vvencapp --help` for your specific VVenc version.**

### Example 1: I-frame only with Constant QP

This command encodes the input video with every frame as an I-frame, using a fixed Quantization Parameter (QP).

```bash
vvencapp -i input.yuv -o output.vvc --Size <width>x<height> --Rate <framerate> --IntraPeriod=1 --QP=<qp_value>
```

*   `--QP=<qp_value>`: Sets the constant QP. For example, `--QP=28`. Lower values mean higher quality and larger files; higher values mean lower quality and smaller files. This mode is typically active if no other rate control mode (`--RateControl`) is specified or if `--RateControl=0` (or a similar value indicating QP-based control) is set.

### Example 2: I-frame only with Constant Bitrate (CBR)

This command encodes the input video with every frame as an I-frame, aiming for a target constant bitrate.

```bash
vvencapp -i input.yuv -o output.vvc --Size <width>x<height> --Rate <framerate> --IntraPeriod=1 --RateControl=1 --TargetBitrate=<bitrate_kbps>
```

*   `--RateControl=1`: This is an *assumed* value to enable CBR mode. The actual numeric value or parameter name (e.g., `--RateControlMode=CBR`) might differ. Check `vvencapp --help`.
*   `--TargetBitrate=<bitrate_kbps>`: Sets the desired average bitrate in kilobits per second (e.g., `--TargetBitrate=5000` for 5 Mbps).

### Example 3: I-frame only with Variable Bitrate (VBR)

This command encodes the input video with every frame as an I-frame, aiming for an average target bitrate but allowing for more fluctuations to optimize quality.

```bash
vvencapp -i input.yuv -o output.vvc --Size <width>x<height> --Rate <framerate> --IntraPeriod=1 --RateControl=2 --TargetBitrate=<bitrate_kbps>
```

*   `--RateControl=2`: This is an *assumed* value to enable VBR mode. The actual numeric value or parameter name (e.g., `--RateControlMode=VBR`) might differ. Check `vvencapp --help`.
*   `--TargetBitrate=<bitrate_kbps>`: Sets the desired average bitrate in kilobits per second (e.g., `--TargetBitrate=4000` for 4 Mbps).

Always refer to the output of `vvencapp --help` to confirm the correct parameters and available options for your specific encoder version. The examples above provide a general structure based on common conventions.

## Important Disclaimer

The information provided in this manual, especially regarding command-line parameter names, options, and their specific values (e.g., for rate control modes), is based on general conventions found in video encoding software and is intended for illustrative purposes.

**VVenc is an evolving software, and its specific command-line interface, available options, and their behavior may differ from what is described here. Parameter names can change, and new features or modes may be introduced.**

Therefore, it is **strongly recommended** to:

1.  **Consult the official VVenc documentation** provided by its developers for the most accurate and up-to-date information.
2.  **Always use the built-in help function** of your specific `vvencapp` (or `vvenc`) executable:

    ```bash
    vvencapp --help
    ```

This will provide the definitive list of parameters, their syntax, and their descriptions applicable to your version of the encoder. Relying solely on this manual without cross-referencing with the encoder's own help output may lead to incorrect command usage or unexpected results.
