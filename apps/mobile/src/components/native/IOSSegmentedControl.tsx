/**
 * Segmented control — iOS path uses the real native `UISegmentedControl`
 * surfaced by `@expo/ui`'s `Picker` with `pickerStyle('segmented')`.
 *
 * Rationale:
 *   Per Apple's WWDC25 UIKit session ("Build a UIKit app with the new
 *   design"), the *only* official iOS 26 native primitive for in-content
 *   segmented selection is `UISegmentedControl` — its thumb automatically
 *   adopts the Liquid Glass appearance during interaction once the binary
 *   is compiled against the iOS 26 SDK (Xcode 26+). Apps recompile and
 *   get the new look for free; there is no "Liquid Glass segmented pill"
 *   API to opt into.
 *
 *   The SwiftUI counterpart `Picker(.segmented)` lowers to
 *   `UISegmentedControl` on iOS, so going through `@expo/ui`'s `Picker`
 *   gives us the same real UIKit control — embedded in a
 *   `UIHostingController` by `@expo/ui` `Host`. There is a known issue
 *   (`expo/expo#44739`) that this hosting layer can break the Liquid
 *   Glass adoption in some configurations; we prefer this path anyway
 *   because:
 *     1. It is the actual platform primitive, not a JS-composed
 *        approximation made of `Capsule + glassEffect`.
 *     2. Future SDK fixes to either iOS or `@expo/ui` will land for free.
 *     3. If the bug bites, we fall back to a vendored UIKit bridge in a
 *        separate step (see `react-native-platform-components`), keeping
 *        the public API of this component unchanged.
 *
 * Fallbacks:
 *   - Android: a JS-built track + sliding thumb (`LayoutAnimation`).
 *     SwiftUI / UIKit obviously aren't available.
 *   - iOS < 26: `UISegmentedControl` falls back to its iOS 18 bordered
 *     appearance automatically. Acceptable for the small slice of users
 *     we expect on older iOS.
 */
import { useEffect, useRef, useState } from "react";
import {
    LayoutAnimation,
    Platform,
    Pressable,
    StyleSheet,
    UIManager,
    View,
    type StyleProp,
    type ViewStyle,
} from "react-native";
import { Text, useTheme } from "react-native-paper";
import {
    Host,
    Picker,
    Text as SwiftUIText,
} from "@expo/ui/swift-ui";
import { pickerStyle, tag } from "@expo/ui/swift-ui/modifiers";

if (
    Platform.OS === "android" &&
    UIManager.setLayoutAnimationEnabledExperimental
) {
    UIManager.setLayoutAnimationEnabledExperimental(true);
}

export type SegmentedOption<V extends string> = {
    value: V;
    label: string;
};

type Props<V extends string> = {
    value: V;
    options: ReadonlyArray<SegmentedOption<V>>;
    onChange: (value: V) => void;
    style?: StyleProp<ViewStyle>;
};

export function IOSSegmentedControl<V extends string>(props: Props<V>) {
    if (Platform.OS === "ios") {
        return <NativeGlassSegmentedControl {...props} />;
    }
    return <FallbackSegmentedControl {...props} />;
}

/**
 * iOS path — `@expo/ui` `Picker` styled with `pickerStyle('segmented')`.
 * SwiftUI's `Picker(.segmented)` lowers to `UISegmentedControl` on iOS,
 * so this renders the real native control. On iOS 26 with Xcode 26 the
 * binary picks up the new Liquid Glass thumb appearance automatically.
 */
const TRACK_HEIGHT = 36;

function NativeGlassSegmentedControl<V extends string>({
    value,
    options,
    onChange,
    style,
}: Props<V>) {
    return (
        <View style={[{ minHeight: TRACK_HEIGHT }, style]}>
            <Host matchContents>
                <Picker
                    selection={value}
                    onSelectionChange={(next) => {
                        if (next !== value) onChange(next as V);
                    }}
                    modifiers={[pickerStyle("segmented")]}
                >
                    {options.map((opt) => (
                        <SwiftUIText
                            key={opt.value}
                            modifiers={[tag(opt.value)]}
                        >
                            {opt.label}
                        </SwiftUIText>
                    ))}
                </Picker>
            </Host>
        </View>
    );
}

/**
 * Android fallback — the same JS-built track + sliding thumb
 * approach we shipped before. Keeps Android visually consistent
 * with what users got pre-Liquid-Glass; SwiftUI obviously isn't
 * available outside iOS.
 */
function FallbackSegmentedControl<V extends string>({
    value,
    options,
    onChange,
    style,
}: Props<V>) {
    const theme = useTheme();
    const isDark = theme.dark;
    const trackBg = isDark
        ? "rgba(118, 118, 128, 0.24)"
        : "rgba(118, 118, 128, 0.12)";
    const thumbBg = isDark ? "#5e5e62" : "#FFFFFF";

    const selectedIdx = Math.max(
        0,
        options.findIndex((o) => o.value === value),
    );

    const prevIdx = useRef(selectedIdx);
    useEffect(() => {
        if (prevIdx.current !== selectedIdx) {
            LayoutAnimation.configureNext({
                duration: 220,
                update: { type: "easeInEaseOut", property: "scaleXY" },
            });
            prevIdx.current = selectedIdx;
        }
    }, [selectedIdx]);

    return (
        <View
            style={[
                {
                    flexDirection: "row",
                    backgroundColor: trackBg,
                    borderRadius: 9,
                    padding: 2,
                    alignSelf: "stretch",
                    position: "relative",
                    minHeight: 36,
                },
                style,
            ]}
        >
            <View
                pointerEvents="none"
                style={[StyleSheet.absoluteFillObject, { padding: 2 }]}
            >
                <View
                    style={{
                        width: `${100 / options.length}%`,
                        marginLeft: `${(100 / options.length) * selectedIdx}%`,
                        height: "100%",
                        borderRadius: 7,
                        backgroundColor: thumbBg,
                    }}
                />
            </View>

            {options.map((opt) => {
                const selected = opt.value === value;
                return (
                    <Pressable
                        key={opt.value}
                        onPress={() => {
                            if (opt.value !== value) onChange(opt.value);
                        }}
                        style={({ pressed }) => ({
                            flex: 1,
                            alignItems: "center",
                            justifyContent: "center",
                            paddingVertical: 6,
                            paddingHorizontal: 8,
                            opacity: pressed && !selected ? 0.5 : 1,
                        })}
                        accessibilityRole="button"
                        accessibilityState={{ selected }}
                        accessibilityLabel={opt.label}
                    >
                        <Text
                            variant="labelLarge"
                            numberOfLines={1}
                            style={{
                                color: theme.colors.onBackground,
                                fontWeight: selected ? "600" : "500",
                                fontSize: 13,
                            }}
                        >
                            {opt.label}
                        </Text>
                    </Pressable>
                );
            })}
        </View>
    );
}
