/*******************************************************************************
 * Copyright (c) 2011, 2021 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *  Red Hat Inc
 *******************************************************************************/
package org.eclipse.kura.core.comm;

import static java.util.Objects.requireNonNull;

import java.io.Closeable;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.Buffer;
import java.nio.ByteBuffer;
import java.util.StringJoiner;

import com.fazecast.jSerialComm.SerialPort;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.comm.CommConnection;
import org.eclipse.kura.comm.CommURI;

public class CommConnectionImpl implements CommConnection, Closeable {

    private static final String SEND_MESSAGE = "sendMessage() - {}";
    private static final Logger logger = LogManager.getLogger(CommConnectionImpl.class);

    private final CommURI commUri;
    private SerialPort serialPort;
    private InputStream inputStream;
    private OutputStream outputStream;

    public CommConnectionImpl(final CommURI commUri) throws IOException {

        requireNonNull(commUri);

        this.commUri = commUri;

        final String port = this.commUri.getPort();
        final int baudRate = this.commUri.getBaudRate();
        final int dataBits = this.commUri.getDataBits();
        final int stopBits = this.commUri.getStopBits();
        final int parity = this.commUri.getParity();
        final int flowControl = this.commUri.getFlowControl();
        final int openTimeout = this.commUri.getOpenTimeout();
        final int receiveTimeout = this.commUri.getReceiveTimeout();

        this.serialPort = SerialPort.getCommPort(port);

        try {
            this.serialPort.setComPortParameters(baudRate, mapDataBits(dataBits), mapStopBits(stopBits), mapParity(parity));
            this.serialPort.setFlowControl(mapFlowControl(flowControl));
            final int timeoutMode = receiveTimeout > 0 ? SerialPort.TIMEOUT_READ_BLOCKING : SerialPort.TIMEOUT_NONBLOCKING;
            this.serialPort.setComPortTimeouts(timeoutMode, receiveTimeout, 0);

            if (!this.serialPort.openPort(openTimeout)) {
                throw new IOException("Failed to open serial port " + port);
            }
        } catch (final Exception e) {
            logger.error("Failed to configure COM port", e);
            if (this.serialPort != null) {
                this.serialPort.closePort();
                this.serialPort = null;
            }
            throw new IOException(e);
        }
    }

    @Override
    public CommURI getURI() {
        return this.commUri;
    }

    @Override
    public DataInputStream openDataInputStream() throws IOException {
        return new DataInputStream(openInputStream());
    }

    @Override
    public synchronized InputStream openInputStream() throws IOException {
        checkIfClosed();

        if (this.inputStream == null) {
            this.inputStream = this.serialPort.getInputStream();
        }
        return this.inputStream;
    }

    @Override
    public DataOutputStream openDataOutputStream() throws IOException {
        return new DataOutputStream(openOutputStream());
    }

    @Override
    public synchronized OutputStream openOutputStream() throws IOException {
        checkIfClosed();

        if (this.outputStream == null) {
            this.outputStream = this.serialPort.getOutputStream();
        }
        return this.outputStream;
    }

    @Override
    public synchronized void close() throws IOException {
        if (this.serialPort != null) {
            if (this.inputStream != null) {
                this.inputStream.close();
                this.inputStream = null;
            }
            if (this.outputStream != null) {
                this.outputStream.close();
                this.outputStream = null;
            }

            this.serialPort.closePort();
            this.serialPort = null;
        }
    }

    private static int mapDataBits(final int dataBits) throws IOException {
        switch (dataBits) {
        case CommURI.DATABITS_5:
        case CommURI.DATABITS_6:
        case CommURI.DATABITS_7:
        case CommURI.DATABITS_8:
            return dataBits;
        default:
            throw new IOException("Unsupported data bits value: " + dataBits);
        }
    }

    private static int mapStopBits(final int stopBits) throws IOException {
        switch (stopBits) {
        case CommURI.STOPBITS_1:
            return SerialPort.ONE_STOP_BIT;
        case CommURI.STOPBITS_1_5:
            return SerialPort.ONE_POINT_FIVE_STOP_BITS;
        case CommURI.STOPBITS_2:
            return SerialPort.TWO_STOP_BITS;
        default:
            throw new IOException("Unsupported stop bits value: " + stopBits);
        }
    }

    private static int mapParity(final int parity) throws IOException {
        switch (parity) {
        case CommURI.PARITY_NONE:
            return SerialPort.NO_PARITY;
        case CommURI.PARITY_ODD:
            return SerialPort.ODD_PARITY;
        case CommURI.PARITY_EVEN:
            return SerialPort.EVEN_PARITY;
        case CommURI.PARITY_MARK:
            return SerialPort.MARK_PARITY;
        case CommURI.PARITY_SPACE:
            return SerialPort.SPACE_PARITY;
        default:
            throw new IOException("Unsupported parity value: " + parity);
        }
    }

    private static int mapFlowControl(final int flowControl) {
        int result = SerialPort.FLOW_CONTROL_DISABLED;

        if ((flowControl & CommURI.FLOWCONTROL_RTSCTS_IN) != 0) {
            result |= SerialPort.FLOW_CONTROL_CTS_ENABLED;
        }
        if ((flowControl & CommURI.FLOWCONTROL_RTSCTS_OUT) != 0) {
            result |= SerialPort.FLOW_CONTROL_RTS_ENABLED;
        }
        if ((flowControl & CommURI.FLOWCONTROL_XONXOFF_IN) != 0) {
            result |= SerialPort.FLOW_CONTROL_XONXOFF_IN_ENABLED;
        }
        if ((flowControl & CommURI.FLOWCONTROL_XONXOFF_OUT) != 0) {
            result |= SerialPort.FLOW_CONTROL_XONXOFF_OUT_ENABLED;
        }

        return result;
    }

    private void checkIfClosed() throws IOException {
        if (this.serialPort == null) {
            throw new IOException("Connection is already closed");
        }
    }

    @Override
    public synchronized void sendMessage(byte[] message) throws KuraException, IOException {
        checkIfClosed();

        if (message == null) {
            throw new NullPointerException("Message must not be null");
        }

        logger.debug(SEND_MESSAGE, () -> getBytesAsString(message));

        if (this.outputStream == null) {
            openOutputStream();
        }

        this.outputStream.write(message, 0, message.length);
        this.outputStream.flush();
    }

    @Override
    public synchronized byte[] sendCommand(byte[] command, int timeout) throws KuraException, IOException {
        checkIfClosed();

        if (command == null) {
            throw new NullPointerException("Serial command must not be null");
        }

        logger.debug(SEND_MESSAGE, () -> getBytesAsString(command));

        if (this.outputStream == null) {
            openOutputStream();
        }
        if (this.inputStream == null) {
            openInputStream();
        }

        byte[] dataInBuffer = flushSerialBuffer();
        if (dataInBuffer != null && dataInBuffer.length > 0) {
            logger.warn("eating bytes in the serial buffer input stream before sending command: {}",
                    getBytesAsString(dataInBuffer));
        }
        this.outputStream.write(command, 0, command.length);
        this.outputStream.flush();

        ByteBuffer buffer = getResponse(timeout);
        if (buffer != null) {
            byte[] response = new byte[buffer.limit()];
            buffer.get(response, 0, response.length);
            return response;
        } else {
            return null;
        }
    }

    @Override
    public synchronized byte[] sendCommand(byte[] command, int timeout, int demark) throws KuraException, IOException {
        checkIfClosed();

        if (command == null) {
            throw new NullPointerException("Serial command must not be null");
        }

        logger.debug(SEND_MESSAGE, getBytesAsString(command));

        if (this.outputStream == null) {
            openOutputStream();
        }
        if (this.inputStream == null) {
            openInputStream();
        }

        byte[] dataInBuffer = flushSerialBuffer();
        if (dataInBuffer != null && dataInBuffer.length > 0) {
            logger.warn("eating bytes in the serial buffer input stream before sending command: {}",
                    getBytesAsString(dataInBuffer));
        }
        this.outputStream.write(command, 0, command.length);
        this.outputStream.flush();

        ByteBuffer buffer = getResponse(timeout, demark);
        if (buffer != null) {
            byte[] response = new byte[buffer.limit()];
            buffer.get(response, 0, response.length);
            return response;
        } else {
            return null;
        }
    }

    @Override
    public synchronized byte[] flushSerialBuffer() throws KuraException, IOException {
        checkIfClosed();

        ByteBuffer buffer = getResponse(50);
        if (buffer != null) {
            byte[] response = new byte[buffer.limit()];
            buffer.get(response, 0, response.length);
            return response;
        } else {
            return null;
        }
    }

    private synchronized ByteBuffer getResponse(int timeout) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocate(4096);
        long start = System.currentTimeMillis();

        while (this.inputStream.available() < 1 && System.currentTimeMillis() - start < timeout) {
            try {
                Thread.sleep(10);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        while (this.inputStream.available() >= 1) {
            int c = this.inputStream.read();
            buffer.put((byte) c);
        }

        // The buffer is casted to Buffer for Java8 compatibility
        ((Buffer) buffer).flip();

        return buffer.limit() > 0 ? buffer : null;
    }

    private synchronized ByteBuffer getResponse(int timeout, int demark) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocate(4096);
        long start = System.currentTimeMillis();

        while (this.inputStream.available() < 1 && System.currentTimeMillis() - start < timeout) {
            try {
                Thread.sleep(10);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        start = System.currentTimeMillis();
        do {
            if (this.inputStream.available() > 0) {
                start = System.currentTimeMillis();
                int c = this.inputStream.read();
                buffer.put((byte) c);
            }
        } while (System.currentTimeMillis() - start < demark);

        // The buffer is casted to Buffer for Java8 compatibility
        ((Buffer) buffer).flip();

        return buffer.limit() > 0 ? buffer : null;
    }

    /* default */ static String getBytesAsString(byte[] bytes) {
        if (bytes == null) {
            return null;
        }

        StringJoiner sj = new StringJoiner(" ");

        for (byte b : bytes) {
            sj.add(String.format("%02X", b));
        }

        return sj.toString();
    }
}
