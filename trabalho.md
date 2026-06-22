A Prefeitura de uma grande cidade deseja criar uma plataforma para registrar e
acompanhar ocorrências urbanas reportadas por cidadãos e sensores IoT.
Exemplos de eventos:
• Acidentes de trânsito;
• Alagamentos;
• Quedas de energia;
• Incêndios;
• Problemas no transporte público;
• Vazamentos de água;
• Interdições de vias;
• Deslizamentos de terra;

• Tiroteios.
Os eventos devem ser armazenados e consultados em tempo real. O sistema deverá
suportar milhares de registros e continuar funcionando mesmo quando um dos servidores
do banco de dados estiver indisponível.

Para isso, podemos usar o banco de dados distribuido apache cassandra?

Cada evento deverá possuir os seguintes atributos no minimo:
{
"idEvento": "EVT00001",
"tipo": "Alagamento",
"descricao": "Rua completamente interditada",
"dataHora": "2025-06-10T15:30:00",
"gravidade": 4,
"status": "Aberto",
"bairro": "Centro",
"cidade": "Rio de Janeiro",
"localizacao": {
"latitude": -22.9068,
"longitude": -43.1729
},
"reportante": {
"tipo": "Cidadao",
"identificador": "USR001"

}
}

Algumas funcionalidades obrigatorias:
6.1 Inserção
Inserir novos eventos.
Exemplo:
Cadastrar um novo alagamento no bairro Centro.

6.2 Consulta por Tipo
Exemplo:
Listar todos os alagamentos.

6.3 Consulta por Período
Exemplo:
Eventos registrados entre
01/05/2025 e 31/05/2025.

6.4 Consulta Geográfica

Exemplo:
Mostrar todos os eventos
num raio de 5 km.
Observação:
Caso o banco escolhido não possua suporte geoespacial nativo, implementar a filtragem
na aplicação.

6.5 Consulta por Gravidade do Evento
Exemplo:
Eventos com gravidade superior a 3.

6.6 Estatísticas
deve-se produzir consultas que retornem:
Quantidade por tipo
Exemplo:
Tipo Total
Acidente 50
Alagamento 35
Etc...

Quantidade por bairro
Exemplo:
Bairro Total
Centro 420
Tijuca 180

Evolução Temporal
Quantidade de eventos por dia.

7. Parte Distribuída (Obrigatória)
devemos criar um ambiente no docker com 3 nós.

Os dados devem existir em mais de um servidor.

Tolerância a Falhas
Procedimento:
1. Inserir dados.
2. Desligar um nó.
3. Executar consultas.
4. Verificar se o sistema continua funcionando.