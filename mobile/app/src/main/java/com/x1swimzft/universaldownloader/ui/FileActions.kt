package com.x1swimzft.universaldownloader.ui

import android.content.Context
import android.content.Intent
import android.net.Uri

private fun mimeOf(context: Context, uri: Uri): String =
    runCatching { context.contentResolver.getType(uri) }.getOrNull() ?: "*/*"

fun openFile(context: Context, uriString: String) {
    val uri = Uri.parse(uriString)
    val intent = Intent(Intent.ACTION_VIEW)
        .setDataAndType(uri, mimeOf(context, uri))
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    runCatching { context.startActivity(intent) }
}

fun shareFile(context: Context, uriString: String) {
    val uri = Uri.parse(uriString)
    val intent = Intent(Intent.ACTION_SEND)
        .setType(mimeOf(context, uri))
        .putExtra(Intent.EXTRA_STREAM, uri)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    runCatching { context.startActivity(Intent.createChooser(intent, null)) }
}
