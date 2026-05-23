import asyncio
from maestro.services.orchestrator import OrchestratorService
from maestro.database.models import OrchestratorDescriptor

class MockRepository:
    async def add(self, descriptor: OrchestratorDescriptor) -> OrchestratorDescriptor:
        descriptor.id = 1
        return descriptor

async def main():
    service = OrchestratorService(repository=MockRepository())
    
    with open("release.example.yaml", "r") as f:
        content = f.read()
        
    try:
        result = await service.save_descriptor(content)
        print("✅ Validação Pydantic realizada com sucesso!")
        print(f"YAML salvo com tamanho: {len(result.yaml)} bytes")
    except ValueError as e:
        print(f"❌ Erro de validação: {e}")

if __name__ == "__main__":
    asyncio.run(main())
