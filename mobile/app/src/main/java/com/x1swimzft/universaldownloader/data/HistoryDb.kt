package com.x1swimzft.universaldownloader.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.x1swimzft.universaldownloader.core.Job

data class HistoryEntry(
    val id: String,
    val title: String,
    val url: String,
    val platform: String,
    val thumbnail: String?,
    val format: String,
    val quality: String,
    val fileUri: String?,
    val sizeBytes: Long?,
    val status: String,
    val createdAt: Long
)

object HistoryDb {
    private const val NAME = "history.db"
    private const val VERSION = 1
    private const val TABLE = "history"

    private var helper: Helper? = null

    fun init(context: Context) {
        if (helper == null) {
            synchronized(this) {
                if (helper == null) helper = Helper(context.applicationContext)
            }
        }
    }

    fun add(context: Context, job: Job) {
        init(context)
        val values = ContentValues().apply {
            put("id", job.id)
            put("title", job.title)
            put("url", job.url)
            put("platform", job.platform)
            put("thumbnail", job.thumbnail)
            put("format", job.format.id)
            put("quality", job.quality)
            put("file_uri", job.fileUri)
            put("size_bytes", job.sizeBytes ?: 0L)
            put("status", job.status.name)
            put("created_at", job.createdAt)
        }
        helper!!.writableDatabase.insertWithOnConflict(TABLE, null, values, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun list(context: Context, limit: Int = 200): List<HistoryEntry> {
        init(context)
        val entries = ArrayList<HistoryEntry>()
        helper!!.readableDatabase.query(
            TABLE, null, null, null, null, null, "created_at DESC", limit.toString()
        ).use { c ->
            while (c.moveToNext()) {
                entries += HistoryEntry(
                    id = c.getString(c.getColumnIndexOrThrow("id")),
                    title = c.getString(c.getColumnIndexOrThrow("title")),
                    url = c.getString(c.getColumnIndexOrThrow("url")),
                    platform = c.getString(c.getColumnIndexOrThrow("platform")),
                    thumbnail = c.getString(c.getColumnIndexOrThrow("thumbnail")),
                    format = c.getString(c.getColumnIndexOrThrow("format")),
                    quality = c.getString(c.getColumnIndexOrThrow("quality")),
                    fileUri = c.getString(c.getColumnIndexOrThrow("file_uri")),
                    sizeBytes = c.getLong(c.getColumnIndexOrThrow("size_bytes")).takeIf { it > 0 },
                    status = c.getString(c.getColumnIndexOrThrow("status")),
                    createdAt = c.getLong(c.getColumnIndexOrThrow("created_at"))
                )
            }
        }
        return entries
    }

    fun delete(context: Context, id: String) {
        init(context)
        helper!!.writableDatabase.delete(TABLE, "id = ?", arrayOf(id))
    }

    fun clear(context: Context) {
        init(context)
        helper!!.writableDatabase.delete(TABLE, null, null)
    }

    private class Helper(context: Context) : SQLiteOpenHelper(context, NAME, null, VERSION) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                """CREATE TABLE $TABLE (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    platform TEXT,
                    thumbnail TEXT,
                    format TEXT,
                    quality TEXT,
                    file_uri TEXT,
                    size_bytes INTEGER,
                    status TEXT,
                    created_at INTEGER
                )"""
            )
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    }
}
