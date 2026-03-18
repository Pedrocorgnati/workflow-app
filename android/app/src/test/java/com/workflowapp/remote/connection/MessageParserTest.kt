package com.workflowapp.remote.connection

import com.workflowapp.remote.model.ControlAckMsg
import com.workflowapp.remote.model.ErrorMsg
import com.workflowapp.remote.model.InteractionRequestMsg
import com.workflowapp.remote.model.InteractiveModeEndedMsg
import com.workflowapp.remote.model.OutputChunkMsg
import com.workflowapp.remote.model.OutputTruncatedMsg
import com.workflowapp.remote.model.PipelineStateMsg
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Unit tests for [MessageParser.parseMessage] — covers TASK-2/ST004 BDD scenarios.
 */
class MessageParserTest {

    private lateinit var parser: MessageParser

    // ── Fixture JSONs ────────────────────────────────────────────────────────

    private val pipelineStateJson = """
        {
            "type": "pipeline_state",
            "message_id": "uuid-001",
            "timestamp": "2024-01-01T00:00:00Z",
            "payload": {
                "status": "running",
                "commands": [
                    {"index": 0, "name": "Task A", "status": "running"},
                    {"index": 1, "name": "Task B", "status": "pending"}
                ]
            }
        }
    """.trimIndent()

    private val outputChunkJson = """
        {
            "type": "output_chunk",
            "message_id": "uuid-002",
            "timestamp": "2024-01-01T00:00:00Z",
            "payload": {"lines": ["line 1", "line 2", "line 3"]}
        }
    """.trimIndent()

    private val interactionJson = """
        {
            "type": "interaction_request",
            "message_id": "uuid-003",
            "timestamp": "2024-01-01T00:00:00Z",
            "payload": {
                "prompt": "Continue?",
                "type": "yes_no",
                "options": ["yes", "no"]
            }
        }
    """.trimIndent()

    @Before fun setUp() {
        parser = MessageParser()
    }

    // ── Cenário 1: valid pipeline_state ──────────────────────────────────────

    @Test fun `valid pipeline_state returns PipelineStateMsg with correct fields`() {
        val result = parser.parseMessage(pipelineStateJson)
        assertNotNull(result)
        assertTrue("Expected PipelineStateMsg", result is PipelineStateMsg)
        val msg = result as PipelineStateMsg
        assertEquals("running", msg.status)
        assertEquals(2, msg.commandQueue.size)
        assertEquals("Task A", msg.commandQueue[0].name)
        assertEquals("pending", msg.commandQueue[1].status)
    }

    // ── Cenário 2: valid output_chunk ────────────────────────────────────────

    @Test fun `valid output_chunk returns OutputChunkMsg with lines`() {
        val result = parser.parseMessage(outputChunkJson)
        assertNotNull(result)
        assertTrue("Expected OutputChunkMsg", result is OutputChunkMsg)
        assertEquals(listOf("line 1", "line 2", "line 3"), (result as OutputChunkMsg).lines)
    }

    // ── Cenário 3: valid interaction_request ─────────────────────────────────

    @Test fun `valid interaction_request returns InteractionRequestMsg`() {
        val result = parser.parseMessage(interactionJson)
        assertNotNull(result)
        assertTrue("Expected InteractionRequestMsg", result is InteractionRequestMsg)
        val msg = result as InteractionRequestMsg
        assertEquals("Continue?", msg.prompt)
        assertEquals("yes_no", msg.type)
        assertEquals(listOf("yes", "no"), msg.options)
    }

    // ── Cenário 4: unknown type returns null ─────────────────────────────────

    @Test fun `unknown type returns null`() {
        val json = """{"type":"unknown_type","message_id":"uuid-004","payload":{}}"""
        assertNull(parser.parseMessage(json))
    }

    // ── Cenário 5: duplicate message_id returns null ──────────────────────────

    @Test fun `duplicate message_id returns null`() {
        assertNotNull(parser.parseMessage(pipelineStateJson))    // first — succeeds
        assertNull(parser.parseMessage(pipelineStateJson))       // second — duplicate
    }

    // ── Cenário 6: malformed JSON returns null without crash ──────────────────

    @Test fun `malformed JSON returns null without crash`() {
        assertNull(parser.parseMessage("not valid json at all"))
        assertNull(parser.parseMessage("{incomplete"))
        assertNull(parser.parseMessage(""))
    }

    // ── Cenário 7: missing required field returns null ────────────────────────

    @Test fun `pipeline_state missing status returns null`() {
        val json = """{"type":"pipeline_state","message_id":"uuid-005","payload":{}}"""
        assertNull(parser.parseMessage(json))
    }

    @Test fun `missing message_id returns null`() {
        val json = """{"type":"output_chunk","payload":{"lines":["line1"]}}"""
        assertNull(parser.parseMessage(json))
    }

    @Test fun `interaction_request missing prompt returns null`() {
        val json = """{"type":"interaction_request","message_id":"uuid-006","payload":{"type":"yes_no"}}"""
        assertNull(parser.parseMessage(json))
    }

    // ── Cenário 8: output_truncated with empty payload ────────────────────────

    @Test fun `output_truncated with empty payload returns linesOmitted=0`() {
        val json = """{"type":"output_truncated","message_id":"uuid-007","payload":{}}"""
        val result = parser.parseMessage(json)
        assertNotNull(result)
        assertTrue("Expected OutputTruncatedMsg", result is OutputTruncatedMsg)
        assertEquals(0, (result as OutputTruncatedMsg).linesOmitted)
    }

    // ── Cenário 9: interactive_mode_ended ────────────────────────────────────

    @Test fun `interactive_mode_ended returns InteractiveModeEndedMsg`() {
        val json = """{"type":"interactive_mode_ended","message_id":"uuid-008","payload":{}}"""
        val result = parser.parseMessage(json)
        assertNotNull(result)
        assertTrue("Expected InteractiveModeEndedMsg", result is InteractiveModeEndedMsg)
        assertEquals("uuid-008", (result as InteractiveModeEndedMsg).messageId)
    }

    // ── Cenário 10: error message ─────────────────────────────────────────────

    @Test fun `error message returns ErrorMsg with message field`() {
        val json = """
            {"type":"error","message_id":"uuid-009","payload":{"message":"Server crash"}}
        """.trimIndent()
        val result = parser.parseMessage(json)
        assertNotNull(result)
        assertTrue("Expected ErrorMsg", result is ErrorMsg)
        assertEquals("Server crash", (result as ErrorMsg).error)
    }

    // ── Cenário 11: control_ack ───────────────────────────────────────────────

    @Test fun `control_ack returns ControlAckMsg with accepted flag`() {
        val json = """
            {"type":"control_ack","message_id":"uuid-010","payload":{"action":"pause","accepted":true}}
        """.trimIndent()
        val result = parser.parseMessage(json)
        assertNotNull(result)
        assertTrue("Expected ControlAckMsg", result is ControlAckMsg)
        val msg = result as ControlAckMsg
        assertEquals("pause", msg.action)
        assertEquals(true, msg.accepted)
    }

    // ── Cenário 12: dedup window size capped at 1000 ──────────────────────────

    @Test fun `after 1001 unique messages seenIds does not exceed 1000`() {
        repeat(1001) { i ->
            val json = """{"type":"output_chunk","message_id":"auto-uuid-$i","payload":{"lines":[]}}"""
            parser.parseMessage(json)
        }
        assertEquals(1000, parser.seenIdsForTest.size)
    }
}
