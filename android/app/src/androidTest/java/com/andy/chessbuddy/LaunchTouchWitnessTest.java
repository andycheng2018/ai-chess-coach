package com.andy.chessbuddy;

import static org.junit.Assert.fail;

import android.content.Intent;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.uiautomator.By;
import androidx.test.uiautomator.BySelector;
import androidx.test.uiautomator.UiDevice;
import androidx.test.uiautomator.UiObject2;
import androidx.test.uiautomator.Until;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.regex.Pattern;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Touch witness on a real Android WebView: launch the release app on a fresh emulator and
 * get from launch to a working home screen using only real screen taps (UiAutomator injects
 * the same touch events a finger does).
 *
 * Born from a live demo where the visitor welcome popup ignored every tap on Android.
 * If anything at launch swallows touches, this test fails and the release is not published.
 *
 * CI runs it on its own fresh emulator (see .github/workflows/android-apk.yml), apart from
 * StandaloneRuntimeTest, because launching the app starts the on-device backend.
 */
@RunWith(AndroidJUnit4.class)
public class LaunchTouchWitnessTest {
    private static final long BOOT_TIMEOUT_MS = 180_000; // Python backend + Stockfish on a cold emulator
    private static final long TAP_TIMEOUT_MS = 8_000;
    private UiDevice device;

    /** WebView exposes a control's label as text or as content description, depending on version. */
    private static BySelector label(String regex) {
        return By.text(Pattern.compile(regex, Pattern.DOTALL));
    }
    private static BySelector description(String regex) {
        return By.desc(Pattern.compile(regex, Pattern.DOTALL));
    }
    private UiObject2 find(String regex, long timeoutMs) {
        long deadline = System.currentTimeMillis() + timeoutMs;
        do {
            UiObject2 found = device.findObject(label(regex));
            if (found == null) found = device.findObject(description(regex));
            if (found != null) return found;
            device.waitForIdle(250);
        } while (System.currentTimeMillis() < deadline);
        return null;
    }
    private boolean gone(String regex, long timeoutMs) {
        return device.wait(Until.gone(label(regex)), timeoutMs) && device.wait(Until.gone(description(regex)), 1_000);
    }
    private String screen() {
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            device.dumpWindowHierarchy(out);
            String xml = out.toString(StandardCharsets.UTF_8.name());
            return xml.length() > 6000 ? xml.substring(0, 6000) + "…" : xml;
        } catch (Exception error) { return "(no hierarchy: " + error + ")"; }
    }
    /** Like find, but scrolls the way a person would until the control is fully on screen. */
    private UiObject2 onScreen(String regex) {
        for (int swipe = 0; swipe <= 8; swipe++) {
            UiObject2 found = find(regex, swipe == 0 ? TAP_TIMEOUT_MS : 1_000);
            if (found == null) return null;
            if (found.getVisibleBounds().height() >= 24) return found; // enough of it to tap
            int w = device.getDisplayWidth(), h = device.getDisplayHeight();
            boolean below = found.getVisibleBounds().top >= h / 2 || found.getVisibleBounds().height() == 0;
            device.swipe(w / 2, below ? h * 3 / 4 : h / 4, w / 2, below ? h / 4 : h * 3 / 4, 20);
            device.waitForIdle(500);
        }
        return find(regex, 1_000);
    }
    /** A real tap at the control's centre, then the screen must change the way a person expects. */
    private void tapAndExpectGone(String control, String disappears, String why) {
        UiObject2 target = onScreen(control);
        if (target == null) fail("Cannot find \"" + control + "\" to tap (" + why + ").\n" + screen());
        target.click();
        if (!gone(disappears, TAP_TIMEOUT_MS)) fail("Tapped \"" + control + "\" but \"" + disappears + "\" is still on screen: " + why + ".\n" + screen());
    }

    @Test public void freshLaunchIsUsableWithRealTaps() {
        device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        Intent intent = new Intent(InstrumentationRegistry.getInstrumentation().getTargetContext(), MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        try (ActivityScenario<MainActivity> ignored = ActivityScenario.launch(intent)) {
            // Launch finishes when either the first-run tablet settings or the home screen is up.
            if (find(".*(Continue to Chess Buddy|Capture Practice).*", BOOT_TIMEOUT_MS) == null) {
                fail("App never reached the tablet settings or home screen.\n" + screen());
            }
            // Clear whatever opened at launch, by touch, in any order (at most a few layers).
            for (int layer = 0; layer < 4; layer++) {
                if (find("Your move\\. Your chess buddy\\.", 1_000) != null) {
                    tapAndExpectGone("Close demo welcome", "Your move\\. Your chess buddy\\.", "the visitor welcome popup must close on tap");
                } else if (find("Continue to Chess Buddy", 1_000) != null) {
                    tapAndExpectGone("Continue to Chess Buddy", "Continue to Chess Buddy", "first-run tablet settings must close on tap");
                } else {
                    break;
                }
            }
            // The home screen must answer touch: open Capture Practice, then close it.
            UiObject2 practice = onScreen(".*Capture Practice.*");
            if (practice == null) fail("Home screen has no Capture Practice button.\n" + screen());
            practice.click();
            if (find("One move\\. One big capture\\.", TAP_TIMEOUT_MS) == null) {
                fail("Tapped Capture Practice but it did not open: the home screen ignores touch.\n" + screen());
            }
            tapAndExpectGone("Close Capture Practice", "One move\\. One big capture\\.", "Capture Practice must close on tap");
        }
    }
}
