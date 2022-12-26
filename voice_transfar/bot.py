
import asyncio
import select
import threading
import time
import logging
import toml

import discord
from discord import opus
from discord.ext import commands
from mixer import MixerManager

logging.basicConfig(level=logging.WARN)

mixer = MixerManager()
config = toml.load(open("config.toml"))
TRANSMITTER_TOKEN = config["TRANSMITTER_TOKEN"]
RECIVER_TOKEN = config["RECIVER_TOKEN"]
GUILD_ID = config["GUILD_ID"]

class Transfer(commands.Cog):
    def __init__(self, reciver: commands.Bot, transmitter: commands.Bot) -> None:
        self.bot_trans = transmitter
        self.bot_recv = reciver
        self.transmitting = False
        self.vc = None
        self.mixer = None
        self.command_ch = None
        self.paused = False

    @commands.slash_command(
        name="transfer",
        description="あなたが参加しているボイスチャンネルに音声転送を開始します。",
        guild_ids=[GUILD_ID],
    )
    async def transfer(
        self,
        ctx: commands.context,
        from_ch_name: discord.Option(
            str,
            required=True,
            description="転送元のボイスチャンネル名",
        ),
    ):
        try:
            guild = await discord.utils.get_or_fetch(
                self.bot_trans, "guild", ctx.guild.id
            )
        except discord.NotFound:
            embed = discord.Embed(title="Error",description="転送元のボットがサーバーに参加していません",color=0xed4245)
            await ctx.respond(embed=embed)
            return

        if self.transmitting:
            self.stop_transfar()

        voice = ctx.author.voice
        self.command_ch = ctx.channel
        channel = discord.utils.get(guild.voice_channels, name=from_ch_name)
        if channel is None:
            embed = discord.Embed(title="Error",description=f"ボイスチャンネル {from_ch_name} が見つかりませんでした",color=0xed4245)
            await ctx.respond(embed=embed)
            return

        if voice.channel == channel:
            embed = discord.Embed(title="Error",description="転送元と転送先が同じです",color=0xed4245)
            await ctx.respond(embed=embed)
            return

        # connect reciver
        self.recv_vc = await voice.channel.connect()
        # connect transmitter
        self.trans_vc = await channel.connect()

        self.mixer = mixer
        await self.start_transfar()
        embed = discord.Embed(title="Success",description="転送が開始されました",color=0x4bb543)
        await ctx.respond(embed=embed)

    @commands.slash_command(name="stop", guild_ids=[GUILD_ID])
    async def stop(self, ctx: commands.context):
        self.stop_transfar()
        await self.recv_vc.disconnect(force=True)
        await self.trans_vc.disconnect(force=True)

        embed = discord.Embed(title="Success",description="転送を停止しました",color=0x4bb543)
        await ctx.respond(embed=embed)

    def recv_decoded_audio(self, data):
        while data.ssrc not in self.trans_vc.ws.ssrc_map:
            time.sleep(0.05)

        user = self.trans_vc.ws.ssrc_map[data.ssrc]["user_id"]
        self.mixer.add_vc_data((user, time.perf_counter(), data.decoded_data))

    def stop_transfar(self):
        self.transmitting = False
        self.trans_vc.decoder.stop()
        if self.mixer:
            self.mixer.stop()
            self.mixer = None

    def recv_audio(self):
        self.trans_vc.starting_time = time.perf_counter()

        while self.transmitting:
            ready, _, err = select.select(
                [self.trans_vc.socket], [], [self.trans_vc.socket], 0.01
            )
            if not ready:
                if err:
                    print(f"Socket error: {err}")
                continue

            try:
                data = self.trans_vc.socket.recv(4096)
            except OSError:
                continue

            self.trans_vc.unpack_audio(data)

    async def start_transfar(self):
        if self.transmitting:
            return

        self.trans_vc.empty_socket()
        self.mixer.reciver_vc = self.recv_vc
        self.mixer.start()

        self.trans_vc.decoder = opus.DecodeManager(self)
        self.trans_vc.decoder.start()
        self.transmitting = True

        t = threading.Thread(
            target=self.recv_audio,
        )
        t.start()


intents = discord.Intents.default()
intents.message_content = True

transmitter = commands.Bot(intents=intents)
reciver = commands.Bot(command_prefix="?", intents=intents)


def main():
    reciver.add_cog(Transfer(reciver, transmitter))
    loop = asyncio.get_event_loop()
    loop.create_task(reciver.start(config["RECIVER_TOKEN"]))
    loop.create_task(transmitter.start(config["TRANSMITTER_TOKEN"]))
    try:
        loop.run_forever()
    finally:
        loop.stop()


if __name__ == "__main__":
    main()
