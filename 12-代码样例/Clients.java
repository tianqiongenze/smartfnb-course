package com.smartfnb.portal;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;
import org.springframework.web.reactive.function.client.WebClient;

/** 下游客户端装配: recipe/inventory(REST) + agent(SSE) */
@Configuration
public class Clients {

    @Bean
    public RestClient recipeClient(@Value("${app.recipe-url}") String base) {
        return RestClient.builder().baseUrl(base).build();
    }

    @Bean
    public RestClient inventoryClient(@Value("${app.inventory-url}") String base) {
        return RestClient.builder().baseUrl(base).build();
    }

    @Bean
    public WebClient agentWebClient(@Value("${app.agent-url}") String base) {
        // JDK HttpClient 会在 SSE 请求上附加 Connection: Upgrade/Upgrade: h2c（HTTP/2 协议升级），
        // 而 Litestar/uvicorn 端会把该请求按升级语义解析导致 body 校验 400（D-06）。
        // 显式指定 Reactor Netty 连接器（HTTP/1.1, 无升级头）——ADR-0016。
        return WebClient.builder()
                .baseUrl(base)
                .clientConnector(new org.springframework.http.client.reactive.JdkClientHttpConnector(
                        java.net.http.HttpClient.newBuilder().version(java.net.http.HttpClient.Version.HTTP_1_1).build()))
                .build();
    }
}
