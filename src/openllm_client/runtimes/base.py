# Copyright 2023 BentoML Team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import typing as t
from abc import abstractmethod

import bentoml

import openllm

if t.TYPE_CHECKING:

    class AnnotatedClient(bentoml.client.Client):
        def health(self, *args: t.Any, **attrs: t.Any) -> t.Any:
            ...

        async def async_health(self) -> t.Any:
            ...

        def call(self, name: str, inputs: t.Any, **attrs: t.Any) -> t.Any:
            ...

        async def async_call(self, name: str, inputs: t.Any, **attrs: t.Any) -> t.Any:
            ...

        def generate_v1(self, qa: openllm.GenerationInput) -> dict[str, t.Any]:
            ...

        def metadata_v1(self) -> dict[str, t.Any]:
            ...


class ClientMixin:
    _api_version: str
    _config_class: type[bentoml.client.Client]

    _host: str
    _port: str

    __client__: AnnotatedClient | None = None
    __llm__: openllm.LLM | None = None

    def __init__(self, address: str, timeout: int = 30):
        self._address = address
        self._timeout = timeout
        assert self._host and self._port, "Make sure to setup _host and _port based on your client implementation."
        self._metadata = self.call("metadata")

    def __init_subclass__(cls, *, client_type: t.Literal["http", "grpc"] = "http", api_version: str = "v1"):
        cls._config_class = bentoml.client.HTTPClient if client_type == "http" else bentoml.client.GrpcClient
        cls._api_version = api_version

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def framework(self) -> t.Literal["pt", "flax", "tf"]:
        raise NotImplementedError

    @property
    def llm(self) -> openllm.LLM:
        if self.__llm__ is None:
            if self.framework == "flax":
                self.__llm__ = openllm.AutoFlaxLLM.for_model(self.model_name)
            elif self.framework == "tf":
                self.__llm__ = openllm.AutoTFLLM.for_model(self.model_name)
            else:
                self.__llm__ = openllm.AutoLLM.for_model(self.model_name)
        return self.__llm__

    @property
    def config(self) -> openllm.LLMConfig:
        return self.llm.config

    def call(self, name: str, *args: t.Any, **attrs: t.Any) -> t.Any:
        return self._cached.call(f"{name}_{self._api_version}", *args, **attrs)

    async def acall(self, name: str, *args: t.Any, **attrs: t.Any) -> t.Any:
        return await self._cached.async_call(f"{name}_{self._api_version}", *args, **attrs)

    @property
    def _cached(self) -> AnnotatedClient:
        if self.__client__ is None:
            self._config_class.wait_until_server_ready(self._host, int(self._port), timeout=self._timeout)
            self.__client__ = t.cast("AnnotatedClient", self._config_class.from_url(self._address))
        return self.__client__


class BaseClient(ClientMixin):
    def health(self) -> t.Any:
        raise NotImplementedError

    def query(self, prompt: str, **attrs: t.Any) -> dict[str, t.Any] | str:
        return_raw_response = attrs.pop("return_raw_response", False)
        prompt, attrs = self.llm.preprocess_parameters(prompt, **attrs)
        inputs = openllm.GenerationInput(prompt=prompt, llm_config=self.config.model_construct_env(**attrs))
        r = openllm.GenerationOutput(**self.call("generate", inputs))

        if return_raw_response:
            return r.model_dump()

        return self.llm.postprocess_parameters(prompt, r.responses)

    # NOTE: Scikit interface
    def predict(self, prompt: str, **attrs: t.Any) -> t.Any:
        return self.query(prompt, **attrs)

    def chat(self, prompt: str, history: list[str], **attrs: t.Any) -> str:
        raise NotImplementedError


class BaseAsyncClient(ClientMixin):
    async def health(self) -> t.Any:
        raise NotImplementedError

    async def query(self, prompt: str, **attrs: t.Any) -> dict[str, t.Any] | str:
        return_raw_response = attrs.pop("return_raw_response", False)
        prompt, attrs = self.llm.preprocess_parameters(prompt, **attrs)
        inputs = openllm.GenerationInput(prompt=prompt, llm_config=self.config.model_construct_env(**attrs))
        res = await self.acall("generate", inputs)
        r = openllm.GenerationOutput(**res)

        if return_raw_response:
            return r.model_dump()

        return self.llm.postprocess_parameters(prompt, r.responses)

    # NOTE: Scikit interface
    async def predict(self, prompt: str, **attrs: t.Any) -> t.Any:
        return await self.query(prompt, **attrs)

    def chat(self, prompt: str, history: list[str], **attrs: t.Any) -> str:
        raise NotImplementedError
