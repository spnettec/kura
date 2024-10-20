/*******************************************************************************
 * Copyright (c) 2018, 2020 Eurotech and/or its affiliates and others
 * 
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 * 
 * SPDX-License-Identifier: EPL-2.0
 * 
 * Contributors:
 *  Eurotech
 *******************************************************************************/

package org.eclipse.kura.example.driver.sensehat;

import java.io.Closeable;
import java.io.IOException;
import java.util.Optional;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledExecutorService;

import org.eclipse.kura.raspberrypi.sensehat.ledmatrix.FrameBufferRaw;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class FramebufferHandler implements Closeable {

    private static final Logger logger = LoggerFactory.getLogger(FramebufferHandler.class);

    private final FrameBufferRaw fb;

    public FramebufferHandler(final FrameBufferRaw fb) {
        this.fb = fb;
    }

    private final ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor();
    private Future<?> writeMessageTask;

    private void cancelWriteMessage() {
        if (this.writeMessageTask != null) {
            this.writeMessageTask.cancel(true);
            this.writeMessageTask = null;
        }
    }

    public synchronized void runFramebufferRequest(final FramebufferRequest request) throws IOException {

        request.getFrontColorRed().ifPresent(color -> {
            this.fb.setFrontColorRed(color);
        });
        request.getFrontColorGreen().ifPresent(color -> {
            this.fb.setFrontColorGreen(color);
        });
        request.getFrontColorBlue().ifPresent(color -> {
            this.fb.setFrontColorBlue(color);
        });

        request.getBackColorRed().ifPresent(color -> {
            this.fb.setBackColorRed(color);
        });
        request.getBackColorGreen().ifPresent(color -> {
            this.fb.setBackColorGreen(color);
        });
        request.getBackColorBlue().ifPresent(color -> {
            this.fb.setBackColorBlue(color);
        });

        request.getTransform().ifPresent(transform -> {
            this.fb.setTransform(transform);
        });

        final Optional<String> writeMessage = request.getMessage();
        final Optional<byte[]> writeRGB565Pixels = request.getRGB565Pixels();
        final Optional<byte[]> writeMonochromePixels = request.getMonochromePixels();

        if (request.shouldClear()) {
            cancelWriteMessage();
            this.fb.clearFrameBuffer();
        } else if (writeRGB565Pixels.isPresent()) {
            cancelWriteMessage();
            this.fb.setPixelsRGB565(writeRGB565Pixels.get());
        } else if (writeMonochromePixels.isPresent()) {
            cancelWriteMessage();
            this.fb.setPixelsMonochrome(writeMonochromePixels.get());
        } else if (writeMessage.isPresent()) {
            cancelWriteMessage();
            this.writeMessageTask = this.executor.submit(() -> {
                try {
                    this.fb.showMessage(writeMessage.get());
                } catch (IOException e) {
                    logger.warn("Failed to write message", e);
                }
            });
        }
    }

    @Override
    public synchronized void close() throws IOException {
        this.fb.closeFrameBuffer();
        this.executor.shutdown();
    }

}
