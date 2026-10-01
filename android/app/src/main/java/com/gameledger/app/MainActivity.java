package com.gameledger.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

/**
 * 应用主窗口：一个全屏 WebView，加载内置资产 www/index.html。
 *
 * 前端在 file:// 协议下自动切换到原生存储桥（见 static/app.js 的
 * NATIVE_MODE 分支）：REST 语义由 GameLedgerBridge 直连应用私有
 * SQLite，无需任何服务器；游戏目录与封面内置在资产目录中，缺失封面
 * 在线回退。
 */
public class MainActivity extends Activity {

    private static final int FILE_CHOOSER_REQUEST = 1001;

    private WebView webView;
    private ValueCallback<Uri[]> filePathCallback;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);          // 主题记忆走 localStorage
        settings.setAllowFileAccess(true);
        // 封面在线回退：file:// 页面加载 https 图片需要跨源许可
        settings.setAllowFileAccessFromFileURLs(true);
        settings.setAllowUniversalAccessFromFileURLs(true);
        webView.setBackgroundColor(0xFF0F1117);        // 深色背景，避免启动白闪
        webView.setOverScrollMode(View.OVER_SCROLL_NEVER);

        webView.addJavascriptInterface(new StorageBridge(this), StorageBridge.JS_NAME);
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient() {
            /** CSV 导入的文件选择：<input type="file"> 需要宿主实现此回调。 */
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                String[] types = params.getAcceptTypes();
                String type = (types != null && types.length > 0 && types[0] != null
                        && !types[0].isEmpty()) ? types[0] : "*/*";
                intent.setType(type);
                try {
                    startActivityForResult(
                            Intent.createChooser(intent, "选择文件"), FILE_CHOOSER_REQUEST);
                } catch (Exception e) {
                    filePathCallback = null;
                    Toast.makeText(MainActivity.this, "没有可用的文件选择器",
                            Toast.LENGTH_SHORT).show();
                    return false;
                }
                return true;
            }
        });
        // 兜底下载通道：前端 CSV 导出优先走 StorageBridge.saveFile，
        // 这里捕获页面内残余的 http(s) 下载请求
        webView.setDownloadListener((url, userAgent, contentDisposition,
                                     mimetype, contentLength) -> {
            try {
                DownloadManager.Request request =
                        new DownloadManager.Request(Uri.parse(url));
                request.setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                DownloadManager manager = getSystemService(DownloadManager.class);
                if (manager != null) {
                    manager.enqueue(request);
                }
            } catch (Exception e) {
                Toast.makeText(MainActivity.this, "下载失败", Toast.LENGTH_SHORT).show();
            }
        });

        webView.loadUrl("file:///android_asset/www/index.html");
        setContentView(webView);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_CHOOSER_REQUEST && filePathCallback != null) {
            filePathCallback.onReceiveValue(
                    WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            filePathCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    /**
     * 返回键：先交给前端（关闭打开中的弹层），前端未处理时 WebView 后退，
     * 都没有则退出应用。
     */
    @Override
    public void onBackPressed() {
        if (webView == null) {
            super.onBackPressed();
            return;
        }
        webView.evaluateJavascript(
                "(window.__onBackPressed ? window.__onBackPressed() : false)",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if ("true".equals(value) || "\"true\"".equals(value)) {
                            return; // 前端已消费（关闭了弹层）
                        }
                        if (webView.canGoBack()) {
                            webView.goBack();
                        } else {
                            finish();
                        }
                    }
                });
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
