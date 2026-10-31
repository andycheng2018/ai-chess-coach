package com.andy.chessbuddy;

import android.app.*;
import android.content.Intent;
import android.os.IBinder;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Keeps the tablet's loopback backend alive with a visible, stoppable notification. */
public class StandaloneService extends Service {
    public static volatile JSONObject state;
    public static volatile String error;
    private static volatile boolean starting;
    private static volatile int generation;
    private static final ExecutorService lifecycle = Executors.newSingleThreadExecutor();
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "stop".equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        StandaloneHost.init(this);
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("chess-runtime", "Chess Buddy local engine", NotificationManager.IMPORTANCE_LOW));
        Intent stop = new Intent(this, StandaloneService.class).setAction("stop");
        PendingIntent action = PendingIntent.getService(this, 1, stop, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, "chess-runtime").setContentTitle("Chess Buddy is running on this tablet")
            .setContentText("Local Stockfish and robot connection · no Mac backend").setSmallIcon(android.R.drawable.ic_dialog_info)
            .addAction(new Notification.Action.Builder(null, "Stop backend", action).build()).setOngoing(true).build();
        startForeground(7, notification);
        synchronized (StandaloneService.class) {
            if (state == null && !starting) {
                starting = true; error = null;
                final int selectedGeneration = ++generation;
                lifecycle.execute(() -> {
                    try {
                        if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                        String engine = getApplicationInfo().nativeLibraryDir + "/libstockfish.so";
                        JSONObject started = new JSONObject(Python.getInstance().getModule("android_backend").callAttr("start", getFilesDir().getAbsolutePath() + "/chessbuddy", engine).toString());
                        if (generation != selectedGeneration) { Python.getInstance().getModule("android_backend").callAttr("stop"); return; }
                        state = started;
                    } catch (Exception exception) { if (generation == selectedGeneration) error = exception.getMessage(); }
                    finally { if (generation == selectedGeneration) starting = false; }
                });
            }
        }
        return START_NOT_STICKY;
    }
    @Override public void onDestroy() {
        generation++; starting = false; state = null; error = "Local backend stopped.";
        lifecycle.execute(() -> { if (Python.isStarted()) try { Python.getInstance().getModule("android_backend").callAttr("stop"); } catch (Exception ignored) {} });
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onTimeout(int startId, int foregroundServiceType) { stopSelf(); }
}
