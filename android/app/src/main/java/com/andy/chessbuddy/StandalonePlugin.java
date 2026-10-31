package com.andy.chessbuddy;

import android.content.Intent;
import androidx.core.content.ContextCompat;
import com.getcapacitor.*;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.chaquo.python.Python;
import org.json.JSONObject;

@CapacitorPlugin(name="StandaloneBackend")
public class StandalonePlugin extends Plugin {
    @Override public void load() { StandaloneHost.init(getContext()); }
    @PluginMethod public void checkForUpdate(PluginCall call) {
        new Thread(() -> {
            try { call.resolve(new JSObject(AndroidUpdates.check().toString())); }
            catch (Exception exception) { call.reject(exception.getMessage()); }
        }, "chess-update-check").start();
    }
    @PluginMethod public void prepareUpdate(PluginCall call) {
        new Thread(() -> {
            try {
                if (Python.isStarted()) Python.getInstance().getModule("android_backend").callAttr("can_configure");
                call.resolve();
            } catch (Exception exception) { call.reject(exception.getMessage()); }
        }).start();
    }
    @PluginMethod public void boot(PluginCall call) {
        ContextCompat.startForegroundService(getContext(), new Intent(getContext(), StandaloneService.class));
        new Thread(() -> {
            try {
                for (int count=0; count<240 && StandaloneService.state == null && StandaloneService.error == null; count++) Thread.sleep(250);
                if (StandaloneService.state == null) throw new Exception(StandaloneService.error == null ? "The local backend did not start in time." : StandaloneService.error);
                JSObject result = new JSObject(StandaloneService.state.toString());
                result.put("settings", new JSONObject(StandaloneHost.publicSettings())); call.resolve(result);
            } catch (Exception exception) { call.reject(exception.getMessage()); }
        }).start();
    }
    @PluginMethod public void configure(PluginCall call) {
        new Thread(() -> {
            try {
                Python.getInstance().getModule("android_backend").callAttr("can_configure");
                StandaloneHost.configure(call.getData().toString());
                Python.getInstance().getModule("android_backend").callAttr("reconfigure");
                call.resolve(new JSObject(StandaloneHost.publicSettings()));
            } catch (Exception exception) { call.reject(exception.getMessage()); }
        }).start();
    }
    @PluginMethod public void publicKey(PluginCall call) {
        new Thread(() -> { try { call.resolve(new JSObject().put("publicKey", StandaloneHost.publicKey())); } catch (Exception exception) { call.reject(exception.getMessage()); } }).start();
    }
    @PluginMethod public void installRobotKey(PluginCall call) {
        final String password = call.getString("password", "");
        if (!Boolean.TRUE.equals(call.getBoolean("confirmed", false)) || password.isEmpty()) { call.reject("Confirm the trusted robot and provide its SSH password for this one-time pairing."); return; }
        new Thread(() -> {
            try {
                Python.getInstance().getModule("android_backend").callAttr("can_configure");
                JSONObject result = new JSONObject(StandaloneHost.installPublicKey(password));
                if (result.getInt("exitCode") != 0) throw new Exception("The robot did not confirm public-key installation.");
                call.resolve(new JSObject().put("ok", true));
            } catch (Exception exception) { call.reject(exception.getMessage()); }
        }).start();
    }
}
