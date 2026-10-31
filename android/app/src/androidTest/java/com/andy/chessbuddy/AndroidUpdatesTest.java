package com.andy.chessbuddy;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class AndroidUpdatesTest {
    private JSONObject release(int code) throws Exception {
        String tag = "android-v" + code;
        return new JSONObject().put("tag_name", tag).put("draft", false).put("prerelease", false)
            .put("assets", new JSONArray().put(new JSONObject().put("name", "ChessBuddy-Standalone-Android.apk")
                .put("size", 12345).put("browser_download_url", AndroidUpdates.REPOSITORY + "/releases/download/" + tag + "/ChessBuddy-Standalone-Android.apk")));
    }

    @Test public void selectsNewestCompleteAndroidReleaseWithoutOfferingDowngrade() throws Exception {
        JSONArray values = new JSONArray().put(release(108)).put(release(110))
            .put(release(109)).put(release(111).put("assets", new JSONArray()))
            .put(release(112).put("tag_name", "desktop-v112"));
        assertEquals(110, AndroidUpdates.selectRelease(values, 107).getInt("versionCode"));
        assertFalse(AndroidUpdates.selectRelease(values, 110).getBoolean("available"));
    }

    @Test public void rejectsUnpublishedOrForeignDownloads() throws Exception {
        JSONObject foreign = release(120);
        foreign.getJSONArray("assets").getJSONObject(0).put("browser_download_url", "https://example.com/untrusted.apk");
        JSONArray values = new JSONArray().put(release(118).put("draft", true))
            .put(release(119).put("prerelease", true)).put(foreign).put(JSONObject.NULL);
        assertFalse(AndroidUpdates.selectRelease(values, 107).getBoolean("available"));
    }
}
