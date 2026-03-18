package com.workflowapp.remote.ui

import androidx.compose.material3.SnackbarDuration
import com.workflowapp.remote.ui.components.FeedbackMessage
import com.workflowapp.remote.ui.components.toSnackbarSpec
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Unit tests for [FeedbackMessage] and [toSnackbarSpec] — module-9 TASK-2 ST004.
 *
 * These are pure-Kotlin tests; no Android instrumentation needed.
 */
class FeedbackSnackbarTest {

    // ── toSnackbarSpec mapping ─────────────────────────────────────────────

    @Test
    fun connectionFailed_hasLongDuration() {
        val (_, duration) = FeedbackMessage.ConnectionFailed.toSnackbarSpec()
        assertEquals(SnackbarDuration.Long, duration)
    }

    @Test
    fun connectionFailed_messageIsNonBlank() {
        val (message, _) = FeedbackMessage.ConnectionFailed.toSnackbarSpec()
        assertTrue(message.isNotBlank(), "ConnectionFailed message must not be blank")
    }

    @Test
    fun responseSent_hasShortDuration() {
        val (_, duration) = FeedbackMessage.ResponseSent.toSnackbarSpec()
        assertEquals(SnackbarDuration.Short, duration)
    }

    @Test
    fun responseSent_messageIsNonBlank() {
        val (message, _) = FeedbackMessage.ResponseSent.toSnackbarSpec()
        assertTrue(message.isNotBlank(), "ResponseSent message must not be blank")
    }

    @Test
    fun responseConsumedByPC_hasShortDuration() {
        val (_, duration) = FeedbackMessage.ResponseConsumedByPC.toSnackbarSpec()
        assertEquals(SnackbarDuration.Short, duration)
    }

    @Test
    fun responseConsumedByPC_messageIsNonBlank() {
        val (message, _) = FeedbackMessage.ResponseConsumedByPC.toSnackbarSpec()
        assertTrue(message.isNotBlank(), "ResponseConsumedByPC message must not be blank")
    }

    @Test
    fun reconnecting_hasIndefiniteDuration() {
        val (_, duration) = FeedbackMessage.Reconnecting.toSnackbarSpec()
        assertEquals(SnackbarDuration.Indefinite, duration)
    }

    @Test
    fun reconnecting_messageIsNonBlank() {
        val (message, _) = FeedbackMessage.Reconnecting.toSnackbarSpec()
        assertTrue(message.isNotBlank(), "Reconnecting message must not be blank")
    }

    // ── Exhaustiveness guard ───────────────────────────────────────────────

    @Test
    fun allFeedbackMessages_haveDistinctMessages() {
        val messages = listOf(
            FeedbackMessage.ConnectionFailed,
            FeedbackMessage.ResponseSent,
            FeedbackMessage.ResponseConsumedByPC,
            FeedbackMessage.Reconnecting,
        ).map { it.toSnackbarSpec().first }

        assertEquals(
            messages.size,
            messages.toSet().size,
            "All FeedbackMessage types must have distinct Snackbar messages",
        )
    }

    @Test
    fun reconnecting_isTheOnlyIndefiniteMessage() {
        val allMessages = listOf(
            FeedbackMessage.ConnectionFailed,
            FeedbackMessage.ResponseSent,
            FeedbackMessage.ResponseConsumedByPC,
            FeedbackMessage.Reconnecting,
        )
        val indefiniteMessages = allMessages.filter {
            it.toSnackbarSpec().second == SnackbarDuration.Indefinite
        }
        assertEquals(1, indefiniteMessages.size)
        assertEquals(FeedbackMessage.Reconnecting, indefiniteMessages.first())
    }
}
