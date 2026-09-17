package com.bank.appbackend.chat;

import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManagerBuilder;
import org.apache.hc.client5.http.ssl.SSLConnectionSocketFactoryBuilder;
import org.apache.hc.core5.http.io.SocketConfig;
import org.apache.hc.core5.ssl.SSLContextBuilder;
import org.apache.hc.core5.util.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;

/**
 * RestClient for PAF. Every chat turn carries a session token and the integration
 * key over this connection, so it verifies PAF's certificate and its hostname.
 *
 * <p>PAF issues that certificate during its own install wizard, which runs long
 * after this tier is built, so the trust anchor arrives afterwards as a file —
 * the same delivery that carries the integration key. Without it the JVM's
 * default trust store applies and PAF calls fail, which is the honest state: the
 * hop cannot be verified until the certificate is in place.
 */
@Configuration
public class PafClientConfig {

    private static final Logger log = LoggerFactory.getLogger(PafClientConfig.class);

    @Bean
    RestClient pafRestClient(@Value("${paf.base-url}") String baseUrl,
                             @Value("${paf.trust-cert:}") String trustCert) throws Exception {
        var sslContext = SSLContextBuilder.create();
        if (trustCert.isBlank()) {
            log.warn("paf.trust-cert is unset — PAF's certificate is not trusted and chat turns "
                    + "will fail on TLS. Deliver it with `manage.py paf push-key`.");
        } else {
            sslContext.loadTrustMaterial(trustAnchor(Path.of(trustCert)), null);
        }
        // The default hostname verifier applies: PAF's certificate names the host
        // paf.base-url addresses it by.
        var sslSocketFactory = SSLConnectionSocketFactoryBuilder.create()
                .setSslContext(sslContext.build())
                .build();
        // A CHAT_FLOW turn runs several agents in sequence; long runs reach a few minutes and
        // creep higher under load, so the socket read timeout sits above that. It also sits
        // under the conversation bench's per-turn ceiling (TURN_TIMEOUT, 300 s), so a turn
        // the bench gives up on has already been logged here with its cause, and a hung
        // turn frees its executor thread before the next customer message queues behind it.
        var connectionManager = PoolingHttpClientConnectionManagerBuilder.create()
                .setSSLSocketFactory(sslSocketFactory)
                .setDefaultSocketConfig(SocketConfig.custom()
                        .setSoTimeout(Timeout.ofMinutes(4))
                        .build())
                .build();
        // PafClient authenticates with a Bearer key and carries no session state, so disable
        // Apache's automatic cookie store to keep any incidental Set-Cookie from PAF unused.
        CloseableHttpClient httpClient = HttpClients.custom()
                .setConnectionManager(connectionManager)
                .disableCookieManagement()
                .build();
        var requestFactory = new HttpComponentsClientHttpRequestFactory(httpClient);
        return RestClient.builder()
                .baseUrl(baseUrl)
                .requestFactory(requestFactory)
                .build();
    }

    /** PAF's certificate is self-signed, so it is its own trust anchor. */
    private static KeyStore trustAnchor(Path pem) throws Exception {
        try (InputStream in = Files.newInputStream(pem)) {
            X509Certificate cert = (X509Certificate) CertificateFactory
                    .getInstance("X.509").generateCertificate(in);
            KeyStore store = KeyStore.getInstance(KeyStore.getDefaultType());
            store.load(null, null);
            store.setCertificateEntry("paf", cert);
            log.info("Trusting PAF certificate {} from {}", cert.getSubjectX500Principal(), pem);
            return store;
        }
    }
}
