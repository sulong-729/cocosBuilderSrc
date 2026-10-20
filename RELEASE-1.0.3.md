# cocos builder 1.0.3

- Reuse successful Android Cocos exports when project, configuration, Creator and
  engine inputs match. Changes detected during export prevent cache reuse.
- Preserve Gradle incremental outputs, enable its build cache and reuse a compatible
  Java daemon. Avoid rewriting unchanged Gradle inputs.
- Add **Buộc xuất lại Cocos Android (bỏ qua cache export)** for a fresh export.
- Run Creator through a private macOS accessory worker without an additional
  editor window or Dock tab. The installed Creator remains unchanged; built-in
  engine paths reuse that installation and custom engine preferences are respected.
- Log cache HIT/MISS and separate export, Gradle and total build timings.

## Validation and limits

146 automated checks passed. On cc30-kproject-c99 with Creator 3.7.3, consecutive
APK-only builds took 96.71 seconds (export required) and 9.10 seconds (cache HIT,
zero export commands). Further cache-hit builds took approximately 9 seconds.
During export, macOS reported zero onscreen worker windows and accessory activation
policy. These checks do not add device-installation or gameplay verification.

The Apple Silicon / macOS 14.4+ installer uses the same development profile as
1.0.2: ad-hoc app signature, unsigned PKG, no Developer ID notarization.
The installer is published on the `dowload-v103` branch of
[sulong-729/installer-cocos-builder-duo-native](https://github.com/sulong-729/installer-cocos-builder-duo-native/tree/dowload-v103).
