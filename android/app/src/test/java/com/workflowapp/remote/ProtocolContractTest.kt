package com.workflowapp.remote

import com.workflowapp.remote.connection.MessageParser
import com.workflowapp.remote.model.ControlAckMsg
import com.workflowapp.remote.model.ErrorMsg
import com.workflowapp.remote.model.InteractionRequestMsg
import com.workflowapp.remote.model.InteractiveModeEndedMsg
import com.workflowapp.remote.model.OutputChunkMsg
import com.workflowapp.remote.model.OutputTruncatedMsg
import com.workflowapp.remote.model.PipelineStateMsg
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Testes de contrato do protocolo JSON — module-11-contract-testing / TASK-1.
 *
 * Valida que [MessageParser] lida corretamente com todos os 10 tipos de mensagem
 * do protocolo bidirecional PC↔Android.
 *
 * Nota sobre a API:
 * - [MessageParser.parseMessage] → processa os 7 tipos PC→Android com whitelist + dedup
 * - [MessageParser.parse]        → parsing raw backward-compatible (sem whitelist)
 *
 * Os 3 tipos Android→PC (control, interaction_response, sync_request) são enviados
 * pelo Android, não recebidos — portanto testados via [parse] (raw) e [serialize].
 */
class ProtocolContractTest {

    private lateinit var parser: MessageParser

    @Before
    fun setUp() {
        parser = MessageParser()
    }

    // ── Fixtures (idênticos ao VALID_ENVELOPES Python de TASK-0) ────────────

    private val outputChunkJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440000","type":"output_chunk","timestamp":"2025-01-15T10:30:00.123456Z","payload":{"lines":["linha 1","linha 2"]}}"""
    private val outputTruncatedJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440001","type":"output_truncated","timestamp":"2025-01-15T10:30:00.123456Z","payload":{"lines_omitted":42}}"""
    private val pipelineStateJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440002","type":"pipeline_state","timestamp":"2025-01-15T10:30:00.123456Z","payload":{"status":"running","command_queue":[{"index":0,"name":"build","status":"running"}]}}"""
    private val interactionRequestJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440003","type":"interaction_request","timestamp":"2025-01-15T10:30:00.123456Z","payload":{"prompt":"Continuar?","type":"confirm","options":["yes","no"]}}"""
    private val interactiveModeEndedJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440004","type":"interactive_mode_ended","timestamp":"2025-01-15T10:30:00.123456Z","payload":{}}"""
    private val errorJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440005","type":"error","timestamp":"2025-01-15T10:30:00.123456Z","payload":{"message":"Erro ao executar comando"}}"""
    private val controlAckJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440006","type":"control_ack","timestamp":"2025-01-15T10:30:00.123456Z","payload":{"action":"pause","accepted":true}}"""
    // Android→PC — parsed via parse() since parseMessage() whitelist is PC→Android only
    private val controlJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440007","type":"control","timestamp":"2025-01-15T10:30:00.123456Z","payload":{"action":"pause"}}"""
    private val interactionResponseJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440008","type":"interaction_response","timestamp":"2025-01-15T10:30:00.123456Z","payload":{"text":"sim","response_type":"yes"}}"""
    private val syncRequestJson =
        """{"message_id":"550e8400-e29b-41d4-a716-446655440009","type":"sync_request","timestamp":"2025-01-15T10:30:00.123456Z","payload":{}}"""

    // ── Cenário 1: output_chunk parseado corretamente ─────────────────────────

    @Test
    fun `output_chunk e parseado para OutputChunkMsg com campos corretos`() {
        val result = parser.parseMessage(outputChunkJson)
        assertNotNull(result)
        assertTrue("Expected OutputChunkMsg", result is OutputChunkMsg)
        val msg = result as OutputChunkMsg
        assertEquals(listOf("linha 1", "linha 2"), msg.lines)
        assertTrue(msg.messageId.isNotEmpty())
    }

    // ── Cenário 2: Todos os 7 tipos PC→Android são parseados ─────────────────

    @Test
    fun `todos os 7 tipos PC para Android sao parseados sem excecao`() {
        val pcFixtures = listOf(
            outputChunkJson,
            outputTruncatedJson,
            pipelineStateJson,
            interactionRequestJson,
            interactiveModeEndedJson,
            errorJson,
            controlAckJson,
        )
        pcFixtures.forEach { raw ->
            val result = parser.parseMessage(raw)
            assertNotNull("parseMessage() falhou para: $raw", result)
        }
    }

    // ── Cenário 3: Tipos Android→PC podem ser parseados via parse() ──────────

    @Test
    fun `tipos Android para PC sao parseados via parse() backward-compat`() {
        val androidFixtures = listOf(controlJson, interactionResponseJson, syncRequestJson)
        androidFixtures.forEach { raw ->
            val envelope = parser.parse(raw)
            assertNotNull("parse() falhou para: $raw", envelope)
            assertTrue(envelope!!.messageId.isNotEmpty())
            assertTrue(envelope.type.isNotEmpty())
        }
    }

    // ── Cenário 4: Consistência cross-platform ────────────────────────────────

    @Test
    fun `output_chunk parseado tem valores identicos aos fixtures Python`() {
        val msg = parser.parseMessage(outputChunkJson) as? OutputChunkMsg
        assertNotNull(msg)
        assertEquals("550e8400-e29b-41d4-a716-446655440000", msg!!.messageId)
        assertEquals(listOf("linha 1", "linha 2"), msg.lines)
    }

    @Test
    fun `pipeline_state parseado tem status e commands corretos`() {
        val msg = parser.parseMessage(pipelineStateJson) as? PipelineStateMsg
        assertNotNull(msg)
        assertEquals("running", msg!!.status)
        assertEquals(1, msg.commandQueue.size)
        assertEquals("build", msg.commandQueue[0].name)
    }

    @Test
    fun `control_ack parseado tem action e accepted corretos`() {
        val msg = parser.parseMessage(controlAckJson) as? ControlAckMsg
        assertNotNull(msg)
        assertEquals("pause", msg!!.action)
        assertTrue(msg.accepted)
    }

    // ── Cenário 5: Rejeição — campo obrigatório faltando ─────────────────────

    @Test
    fun `pipeline_state sem status retorna null`() {
        val bad = """{"message_id":"id-bad-001","type":"pipeline_state","timestamp":"2025-01-15T10:30:00Z","payload":{}}"""
        assertNull(parser.parseMessage(bad))
    }

    @Test
    fun `interaction_request sem prompt retorna null`() {
        val bad = """{"message_id":"id-bad-002","type":"interaction_request","timestamp":"2025-01-15T10:30:00Z","payload":{"type":"confirm"}}"""
        assertNull(parser.parseMessage(bad))
    }

    // ── Cenário 6: Rejeição — message_id ausente ──────────────────────────────

    @Test
    fun `mensagem sem message_id retorna null`() {
        val bad = """{"type":"output_chunk","timestamp":"2025-01-15T10:30:00Z","payload":{"lines":[]}}"""
        assertNull(parser.parseMessage(bad))
    }

    // ── Cenário 7 (EDGE): Tipo desconhecido via parseMessage() ───────────────

    @Test
    fun `tipo desconhecido retorna null via parseMessage`() {
        val unknown = """{"message_id":"id-unk-001","type":"unknown_type","timestamp":"2025-01-15T10:30:00Z","payload":{}}"""
        assertNull(parser.parseMessage(unknown))
    }

    // ── Cenário 8 (EDGE): JSON malformado não causa crash ────────────────────

    @Test
    fun `json malformado nao causa crash via parseMessage`() {
        assertNull(parser.parseMessage("isso nao e json {{{"))
        assertNull(parser.parseMessage("{incomplete"))
    }

    @Test
    fun `json malformado nao causa crash via parse`() {
        assertNull(parser.parse("isso nao e json {{{"))
        assertNull(parser.parse(""))
    }

    // ── Cenário 9 (DEGRADED): Payload oversized não causa crash ──────────────

    @Test
    fun `output_chunk com payload grande nao causa crash`() {
        val largeLines = (1..50).map { "x".repeat(100) }
        val linesJson = largeLines.joinToString(",") { "\"$it\"" }
        val raw = """{"message_id":"id-large-001","type":"output_chunk","timestamp":"2025-01-15T10:30:00Z","payload":{"lines":[$linesJson]}}"""
        val result = parser.parseMessage(raw)
        assertNotNull(result)
        assertTrue(result is OutputChunkMsg)
        assertEquals(50, (result as OutputChunkMsg).lines.size)
    }

    // ── Forward compatibility: campos extras são ignorados ────────────────────

    @Test
    fun `campos extras no envelope sao ignorados - forward compat`() {
        val raw = """{"message_id":"id-fwd-001","type":"output_chunk","timestamp":"2025-01-15T10:30:00Z","payload":{"lines":[]},"extra_field":"ignore_me","future_feature":{"nested":true}}"""
        val result = parser.parseMessage(raw)
        assertNotNull(result)
        assertTrue(result is OutputChunkMsg)
    }

    // ── output_truncated e interactive_mode_ended ─────────────────────────────

    @Test
    fun `output_truncated com lines_omitted correto`() {
        val msg = parser.parseMessage(outputTruncatedJson) as? OutputTruncatedMsg
        assertNotNull(msg)
        assertEquals(42, msg!!.linesOmitted)
    }

    @Test
    fun `interactive_mode_ended parseado sem crash`() {
        val msg = parser.parseMessage(interactiveModeEndedJson)
        assertNotNull(msg)
        assertTrue(msg is InteractiveModeEndedMsg)
    }

    @Test
    fun `error message tem campo message correto`() {
        val msg = parser.parseMessage(errorJson) as? ErrorMsg
        assertNotNull(msg)
        assertEquals("Erro ao executar comando", msg!!.error)
    }

    @Test
    fun `interaction_request tem prompt e options corretos`() {
        val msg = parser.parseMessage(interactionRequestJson) as? InteractionRequestMsg
        assertNotNull(msg)
        assertEquals("Continuar?", msg!!.prompt)
        assertEquals(listOf("yes", "no"), msg.options)
    }
}
