package com.andy.vbotstudio;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * The screens' only route to the embedded controller. There's no network listener,
 * so other apps on the tablet have nothing to connect to.
 */
@CapacitorPlugin(name = "StudioBackend")
public class StudioPlugin extends Plugin {
    @Override public void load() {
        StudioHost.init(getContext());
        new Thread(() -> { try { backend(); } catch (Exception retriedOnFirstCall) {} }, "vbot-controller-start").start();
    }

    private synchronized PyObject backend() {
        if (!Python.isStarted()) Python.start(new AndroidPlatform(getContext().getApplicationContext()));
        PyObject module = Python.getInstance().getModule("studio_backend");
        module.callAttr("start", getContext().getFilesDir().getAbsolutePath() + "/vbot-app");
        return module;
    }

    private static String operatorMessage(Exception error) {
        String message = String.valueOf(error.getMessage());
        int marker = message.indexOf(StudioHost.REFUSAL);
        return marker >= 0 ? message.substring(marker + StudioHost.REFUSAL.length()).split("\n", 2)[0] : "Pairing failed. Check the dog's address and try again.";
    }

    @PluginMethod public void call(PluginCall call) {
        final String path = call.getString("path", ""), body = call.getString("body", "");
        new Thread(() -> {
            try { call.resolve(new JSObject(backend().callAttr("call", path, body).toString())); }
            catch (Exception error) { call.reject("The app's controller didn't answer."); }
        }, "vbot-controller-call").start();
    }

    @PluginMethod public void pairing(PluginCall call) {
        new Thread(() -> {
            try { call.resolve(new JSObject().put("fingerprint", StudioHost.trustedFingerprint())); }
            catch (Exception error) { call.reject("Couldn't read the saved pairing."); }
        }, "vbot-pairing-read").start();
    }

    /** The password is used for this one call and never stored or logged. */
    @PluginMethod public void pair(PluginCall call) {
        final String target = call.getString("target", ""), fingerprint = call.getString("fingerprint", ""), password = call.getString("password", "");
        if (!Boolean.TRUE.equals(call.getBoolean("confirmed", false)) || password.isEmpty()) {
            call.reject("Confirm the fingerprint and enter the dog's SSH password for this one-time pairing.");
            return;
        }
        new Thread(() -> {
            try {
                backend().callAttr("can_pair");
                StudioHost.pair(target, fingerprint, password);
                call.resolve(new JSObject().put("fingerprint", fingerprint));
            } catch (Exception error) { call.reject(operatorMessage(error)); }
        }, "vbot-pairing").start();
    }
}
