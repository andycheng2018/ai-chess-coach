package com.andy.chessbuddy;

import static org.junit.Assert.*;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.chaquo.python.android.AndroidPlatform;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Runs on a fresh CI emulator, with no cloud credentials or robot pairing. */
@RunWith(AndroidJUnit4.class)
public class StandaloneRuntimeTest {
    private JSONObject request(JSONObject runtime, String path, String payload, boolean authorized) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(runtime.getString("url") + path).openConnection();
        connection.setConnectTimeout(10000); connection.setReadTimeout(30000);
        connection.setRequestProperty("Origin", "https://localhost");
        if (authorized) connection.setRequestProperty("X-Chess-Buddy-Token", runtime.getString("token"));
        if (payload != null) {
            connection.setRequestMethod("POST"); connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            try (var stream = connection.getOutputStream()) { stream.write(payload.getBytes(StandardCharsets.UTF_8)); }
        }
        int status = connection.getResponseCode();
        try {
            if (!authorized) { assertEquals(403, status); return new JSONObject(); }
            String body;
            try (var stream = status < 400 ? connection.getInputStream() : connection.getErrorStream()) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                byte[] buffer = new byte[4096]; int size;
                while ((size = stream.read(buffer)) != -1) bytes.write(buffer, 0, size);
                body = new String(bytes.toByteArray(), StandardCharsets.UTF_8);
            }
            assertEquals(body, 200, status);
            return new JSONObject(body);
        } finally { connection.disconnect(); }
    }

    @Test public void localBackendRunsStockfishAndRestartsWithoutMac() throws Exception {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        StandaloneHost.init(context);
        // Refuse to run against an inhabited tablet with credentials or a paired robot.
        assertEquals("Use a fresh emulator", "{}", StandaloneHost.readSettings());
        if (!Python.isStarted()) Python.start(new AndroidPlatform(context));
        PyObject backend = Python.getInstance().getModule("android_backend");
        for (int cycle = 0; cycle < 2; cycle++) {
            JSONObject runtime = new JSONObject(backend.callAttr("start", context.getCacheDir() + "/runtime-smoke", context.getApplicationInfo().nativeLibraryDir + "/libstockfish.so").toString());
            try {
                request(runtime, "/api/health", null, false);
                assertTrue(request(runtime, "/api/health", null, true).getBoolean("ok"));
                JSONObject result = request(runtime, "/api/analysis/position", "{\"rootFen\":\"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1\",\"moves\":[],\"detail\":\"quick\"}", true);
                assertTrue(result.toString(), result.getJSONArray("lines").length() > 0);
                assertFalse(request(runtime, "/api/vbot/status", null, true).getBoolean("armed"));
            } finally { backend.callAttr("stop"); }
        }
    }
}
