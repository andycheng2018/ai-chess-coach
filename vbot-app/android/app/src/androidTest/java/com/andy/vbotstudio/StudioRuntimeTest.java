package com.andy.vbotstudio;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Runs on a fresh emulator with no pairing and no dog. It proves the embedded controller works. */
@RunWith(AndroidJUnit4.class)
public class StudioRuntimeTest {
    private PyObject backend;

    @Before public void start() {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        StudioHost.init(context);
        if (!Python.isStarted()) Python.start(new AndroidPlatform(context));
        backend = Python.getInstance().getModule("studio_backend");
        backend.callAttr("start", context.getFilesDir().getAbsolutePath() + "/vbot-app-test");
    }

    private JSONObject call(String path, String body) throws Exception {
        return new JSONObject(backend.callAttr("call", path, body).toString());
    }

    @Test public void controllerStartsFaceOnly() throws Exception {
        JSONObject reply = call("status", "");
        assertEquals(200, reply.getInt("status"));
        JSONObject status = reply.getJSONObject("body");
        assertFalse(status.getString("connection").equals("connected"));
        assertFalse(status.getJSONObject("capabilities").getJSONObject("head").getBoolean("available"));
        assertFalse(status.getJSONObject("capabilities").getJSONObject("body").getBoolean("available"));
    }

    @Test public void anUnpairedAppRefusesBeforeUsingTheNetwork() throws Exception {
        assertEquals("", StudioHost.trustedFingerprint());
        JSONObject status = call("connect", "{\"target\":\"192.0.2.1\"}").getJSONObject("body");
        assertEquals("unavailable", status.getString("connection"));
        assertTrue(status.getString("detail"), status.getString("detail").contains("Pair this app"));
    }

    @Test public void aMalformedFingerprintCannotPair() {
        try {
            StudioHost.pair("192.0.2.1", "not-a-fingerprint", "unused");
            throw new AssertionError("Pairing accepted a malformed fingerprint.");
        } catch (Exception refused) {
            assertTrue(String.valueOf(refused.getMessage()), String.valueOf(refused.getMessage()).contains("SHA256"));
        }
    }
}
